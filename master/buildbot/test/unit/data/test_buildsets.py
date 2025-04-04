# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from twisted.internet import defer
from twisted.trial import unittest

from buildbot.data import buildsets
from buildbot.data import resultspec
from buildbot.process.results import FAILURE
from buildbot.process.results import SUCCESS
from buildbot.test import fakedb
from buildbot.test.fake import fakemaster
from buildbot.test.reactor import TestReactorMixin
from buildbot.test.util import endpoint
from buildbot.test.util import interfaces as util_interfaces
from buildbot.util import epoch2datetime

A_TIMESTAMP = 1341700729
A_TIMESTAMP_EPOCH = epoch2datetime(A_TIMESTAMP)
EARLIER = 1248529376
EARLIER_EPOCH = epoch2datetime(EARLIER)


class BuildsetEndpoint(endpoint.EndpointMixin, unittest.TestCase):
    endpointClass = buildsets.BuildsetEndpoint
    resourceTypeClass = buildsets.Buildset

    @defer.inlineCallbacks
    def setUp(self):
        yield self.setUpEndpoint()
        yield self.master.db.insert_test_data([
            fakedb.Buildset(id=13, reason='because I said so'),
            fakedb.SourceStamp(id=92),
            fakedb.SourceStamp(id=93),
            fakedb.BuildsetSourceStamp(buildsetid=13, sourcestampid=92),
            fakedb.BuildsetSourceStamp(buildsetid=13, sourcestampid=93),
            fakedb.Buildset(id=14, reason='no sourcestamps'),
        ])

    @defer.inlineCallbacks
    def test_get_existing(self):
        buildset = yield self.callGet(('buildsets', 13))

        self.validateData(buildset)
        self.assertEqual(buildset['reason'], 'because I said so')

    @defer.inlineCallbacks
    def test_get_existing_no_sourcestamps(self):
        buildset = yield self.callGet(('buildsets', 14))

        self.validateData(buildset)
        self.assertEqual(buildset['sourcestamps'], [])

    @defer.inlineCallbacks
    def test_get_missing(self):
        buildset = yield self.callGet(('buildsets', 99))

        self.assertEqual(buildset, None)


class BuildsetsEndpoint(endpoint.EndpointMixin, unittest.TestCase):
    endpointClass = buildsets.BuildsetsEndpoint
    resourceTypeClass = buildsets.Buildset

    @defer.inlineCallbacks
    def setUp(self):
        yield self.setUpEndpoint()
        yield self.master.db.insert_test_data([
            fakedb.SourceStamp(id=92),
            fakedb.Buildset(id=13, complete=True),
            fakedb.Buildset(id=14, complete=False),
            fakedb.BuildsetSourceStamp(buildsetid=13, sourcestampid=92),
            fakedb.BuildsetSourceStamp(buildsetid=14, sourcestampid=92),
        ])

    @defer.inlineCallbacks
    def test_get(self):
        buildsets = yield self.callGet(('buildsets',))

        self.validateData(buildsets[0])
        self.assertEqual(buildsets[0]['bsid'], 13)
        self.validateData(buildsets[1])
        self.assertEqual(buildsets[1]['bsid'], 14)

    @defer.inlineCallbacks
    def test_get_complete(self):
        f = resultspec.Filter('complete', 'eq', [True])
        buildsets = yield self.callGet(
            ('buildsets',), resultSpec=resultspec.ResultSpec(filters=[f])
        )

        self.assertEqual(len(buildsets), 1)
        self.validateData(buildsets[0])
        self.assertEqual(buildsets[0]['bsid'], 13)

    @defer.inlineCallbacks
    def test_get_incomplete(self):
        f = resultspec.Filter('complete', 'eq', [False])
        buildsets = yield self.callGet(
            ('buildsets',), resultSpec=resultspec.ResultSpec(filters=[f])
        )

        self.assertEqual(len(buildsets), 1)
        self.validateData(buildsets[0])
        self.assertEqual(buildsets[0]['bsid'], 14)


class Buildset(TestReactorMixin, util_interfaces.InterfaceTests, unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        self.setup_test_reactor()
        self.master = yield fakemaster.make_master(self, wantMq=True, wantDb=True, wantData=True)
        self.rtype = buildsets.Buildset(self.master)
        yield self.master.db.insert_test_data([
            fakedb.SourceStamp(
                id=234,
                branch='br',
                codebase='cb',
                project='pr',
                repository='rep',
                revision='rev',
                created_at=89834834,
            ),
            fakedb.Builder(id=42, name='bldr1'),
            fakedb.Builder(id=43, name='bldr2'),
            fakedb.Buildset(id=199, complete=False),
            fakedb.BuildRequest(id=999, buildsetid=199, builderid=42),
        ])

    SS234_DATA = {
        'branch': 'br',
        'codebase': 'cb',
        'patch': None,
        'project': 'pr',
        'repository': 'rep',
        'revision': 'rev',
        'created_at': epoch2datetime(89834834),
        'ssid': 234,
    }

    def test_signature_addBuildset(self):
        @self.assertArgSpecMatches(
            self.master.data.updates.addBuildset,  # fake
            self.rtype.addBuildset,
        )  # real
        def addBuildset(
            self,
            waited_for,
            scheduler=None,
            sourcestamps=None,
            reason='',
            properties=None,
            builderids=None,
            external_idstring=None,
            rebuilt_buildid=None,
            parent_buildid=None,
            parent_relationship=None,
            priority=0,
        ):
            pass

    @defer.inlineCallbacks
    def do_test_addBuildset(self, kwargs, expectedReturn, expectedMessages, expectedBuildset):
        """Run a test of addBuildset.

        @param kwargs: kwargs to addBuildset
        @param expectedReturn: expected return value - tuple of (bsid, brids)
        @param expectedMessages: expected mq messages transmitted
        @param expectedBuildset: expected buildset inserted into the db

        The buildset is added at time A_TIMESTAMP.
        Note that addBuildset does not add sourcestamps, so this method assumes
        there are none in the db.
        """
        self.reactor.advance(A_TIMESTAMP)

        (bsid, brids) = yield self.rtype.addBuildset(**kwargs)
        self.assertEqual((bsid, brids), expectedReturn)

        self.master.mq.assertProductions(expectedMessages, orderMatters=False)

        buildsets = yield self.master.db.buildsets.getBuildsets()
        buildsets = [bs for bs in buildsets if bs.bsid != 199]
        self.assertEqual(
            [
                {
                    'external_idstring': bs.external_idstring,
                    'reason': bs.reason,
                    'rebuilt_buildid': bs.rebuilt_buildid,
                }
                for bs in buildsets
            ],
            [expectedBuildset],
        )

    def _buildRequestMessageDict(self, brid, bsid, builderid):
        return {
            'builderid': builderid,
            'buildrequestid': brid,
            'buildsetid': bsid,
            'claimed': False,
            'claimed_at': None,
            'claimed_by_masterid': None,
            'complete': False,
            'complete_at': None,
            'priority': 0,
            'results': -1,
            'submitted_at': epoch2datetime(A_TIMESTAMP),
            'waited_for': True,
            'properties': None,
        }

    def _buildRequestMessage1(self, brid, bsid, builderid):
        return (
            ('buildsets', str(bsid), 'builders', str(builderid), 'buildrequests', str(brid), 'new'),
            self._buildRequestMessageDict(brid, bsid, builderid),
        )

    def _buildRequestMessage2(self, brid, bsid, builderid):
        return (
            ('buildrequests', str(brid), 'new'),
            self._buildRequestMessageDict(brid, bsid, builderid),
        )

    def _buildRequestMessage3(self, brid, bsid, builderid):
        return (
            ('builders', str(builderid), 'buildrequests', str(brid), 'new'),
            self._buildRequestMessageDict(brid, bsid, builderid),
        )

    def _buildsetMessage(
        self,
        bsid,
        external_idstring='extid',
        reason='because',
        scheduler='fakesched',
        sourcestampids=None,
        submitted_at=A_TIMESTAMP,
    ):
        if sourcestampids is None:
            sourcestampids = [234]
        ssmap = {234: self.SS234_DATA}
        return (
            ('buildsets', str(bsid), 'new'),
            {
                "bsid": bsid,
                "complete": False,
                "complete_at": None,
                "external_idstring": external_idstring,
                "parent_buildid": None,
                "reason": reason,
                "results": None,
                "scheduler": scheduler,
                "sourcestamps": [ssmap[ssid] for ssid in sourcestampids],
                "rebuilt_buildid": None,
                "submitted_at": submitted_at,
            },
        )

    def _buildsetCompleteMessage(
        self,
        bsid,
        complete_at=A_TIMESTAMP_EPOCH,
        submitted_at=A_TIMESTAMP_EPOCH,
        external_idstring='extid',
        reason='because',
        results=0,
        sourcestampids=None,
    ):
        if sourcestampids is None:
            sourcestampids = [234]
        ssmap = {234: self.SS234_DATA}
        return (
            ('buildsets', str(bsid), 'complete'),
            {
                "bsid": bsid,
                "complete": True,
                "complete_at": complete_at,
                "external_idstring": external_idstring,
                "reason": reason,
                "results": results,
                "submitted_at": submitted_at,
                "sourcestamps": [ssmap[ssid] for ssid in sourcestampids],
                "rebuilt_buildid": None,
                "parent_buildid": None,
                "parent_relationship": None,
            },
        )

    def test_addBuildset_two_builderNames(self):
        kwargs = {
            "scheduler": 'fakesched',
            "reason": 'because',
            "sourcestamps": [234],
            "external_idstring": 'extid',
            "builderids": [42, 43],
            "waited_for": True,
        }
        expectedReturn = (200, {42: 1000, 43: 1001})
        expectedMessages = [
            self._buildRequestMessage1(1000, 200, 42),
            self._buildRequestMessage2(1000, 200, 42),
            self._buildRequestMessage3(1000, 200, 42),
            self._buildRequestMessage1(1001, 200, 43),
            self._buildRequestMessage2(1001, 200, 43),
            self._buildRequestMessage3(1001, 200, 43),
            self._buildsetMessage(200),
        ]
        expectedBuildset = {
            "reason": 'because',
            "external_idstring": 'extid',
            "rebuilt_buildid": None,
        }
        return self.do_test_addBuildset(kwargs, expectedReturn, expectedMessages, expectedBuildset)

    def test_addBuildset_no_builderNames(self):
        kwargs = {
            "scheduler": 'fakesched',
            "reason": 'because',
            "sourcestamps": [234],
            "external_idstring": 'extid',
            "waited_for": False,
        }
        expectedReturn = (200, {})
        expectedMessages = [
            self._buildsetMessage(200),
            # with no builderNames, this is done already
            self._buildsetCompleteMessage(200),
        ]
        expectedBuildset = {
            "reason": 'because',
            "external_idstring": 'extid',
            "rebuilt_buildid": None,
        }
        return self.do_test_addBuildset(kwargs, expectedReturn, expectedMessages, expectedBuildset)

    def test_signature_maybeBuildsetComplete(self):
        @self.assertArgSpecMatches(
            self.master.data.updates.maybeBuildsetComplete,  # fake
            self.rtype.maybeBuildsetComplete,
        )  # real
        def maybeBuildsetComplete(self, bsid):
            pass

    @defer.inlineCallbacks
    def do_test_maybeBuildsetComplete(
        self,
        buildRequestCompletions=None,
        buildRequestResults=None,
        buildsetComplete=False,
        expectComplete=False,
        expectMessage=False,
        expectSuccess=True,
    ):
        """Test maybeBuildsetComplete.

        @param buildRequestCompletions: dict mapping brid to True if complete,
            else False (and defaulting to False)
        @param buildRequestResults: dict mapping brid to result (defaulting
            to SUCCESS)
        @param buildsetComplete: true if the buildset is already complete
        @param expectComplete: true if the buildset should be complete at exit
        @param expectMessage: true if a buildset completion message is expected
        @param expectSuccess: if expectComplete, whether to expect the buildset
            to be complete

        This first adds two buildsets to the database - 72 and 73.  Buildset 72
        is already complete if buildsetComplete is true; 73 is not complete.
        It adds four buildrequests - 42, 43, and 44 for buildset 72, and 45 for
        buildset 73.  The completion and results are based on
        buidlRequestCompletions and buildRequestResults.

        Then, maybeBuildsetComplete is called for buildset 72, and the
        expectations are checked.
        """
        if buildRequestCompletions is None:
            buildRequestCompletions = {}
        if buildRequestResults is None:
            buildRequestResults = {}

        self.reactor.advance(A_TIMESTAMP)

        def mkbr(brid, bsid):
            return fakedb.BuildRequest(
                id=brid,
                buildsetid=bsid,
                builderid=42,
                complete=buildRequestCompletions.get(brid, False),
                results=buildRequestResults.get(brid, SUCCESS),
            )

        yield self.master.db.insert_test_data([
            fakedb.Buildset(
                id=72,
                submitted_at=EARLIER,
                complete=buildsetComplete,
                complete_at=A_TIMESTAMP if buildsetComplete else None,
            ),
            mkbr(42, 72),
            mkbr(43, 72),
            mkbr(44, 72),
            fakedb.BuildsetSourceStamp(buildsetid=72, sourcestampid=234),
            fakedb.Buildset(id=73, complete=False),
            mkbr(45, 73),
            fakedb.BuildsetSourceStamp(buildsetid=73, sourcestampid=234),
        ])

        yield self.rtype.maybeBuildsetComplete(72)

        buildset_ids = [
            bs.bsid for bs in (yield self.master.db.buildsets.getBuildsets(complete=expectComplete))
        ]
        self.assertIn(72, buildset_ids)

        if expectMessage:
            self.assertEqual(
                self.master.mq.productions,
                [
                    self._buildsetCompleteMessage(
                        72,
                        results=SUCCESS if expectSuccess else FAILURE,
                        submitted_at=EARLIER_EPOCH,
                    ),
                ],
            )
        else:
            self.assertEqual(self.master.mq.productions, [])

    def test_maybeBuildsetComplete_not_yet(self):
        # only brid 42 is complete, so the buildset is not complete
        return self.do_test_maybeBuildsetComplete(buildRequestCompletions={42: True})

    def test_maybeBuildsetComplete_complete(self):
        return self.do_test_maybeBuildsetComplete(
            buildRequestCompletions={42: True, 43: True, 44: True},
            expectComplete=True,
            expectMessage=True,
        )

    def test_maybeBuildsetComplete_complete_failure(self):
        return self.do_test_maybeBuildsetComplete(
            buildRequestCompletions={42: True, 43: True, 44: True},
            buildRequestResults={43: FAILURE},
            expectComplete=True,
            expectMessage=True,
            expectSuccess=False,
        )

    def test_maybeBuildsetComplete_already_complete(self):
        return self.do_test_maybeBuildsetComplete(
            buildRequestCompletions={42: True, 43: True, 44: True},
            buildsetComplete=True,
            expectComplete=True,
            expectMessage=False,
        )
