# SPDX-License-Identifier: GPL-2.0-only
import errno
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import eeprom_table as p


def packet(length=0):
    return bytes([0x5a,0xa5,1,2,3,4,length])+bytes(i&255 for i in range(length+2))


def words(version=7,date=0xffffffff,common=(),bu=()):
    values={0xe0:version,0x4e1:date,0xffe3:len(common),0xffe7:len(bu)}
    values.update({0xe3+(i<<8):v for i,v in enumerate(common)})
    values.update({0xe7+(i<<8):v for i,v in enumerate(bu)})
    return values


def read(values,replies,max_events=p.MAX_EVENTS):
    scalar=mock.Mock(side_effect=lambda selector:values[selector])
    buffer=mock.Mock(side_effect=replies)
    return p.read_table(scalar,buffer,values[0xe0],max_events),scalar,buffer


class EepromTableTests(unittest.TestCase):
    def test_source_frame_magic_length_and_full_maximum_without_unsafe256_byte_copy(self):
        for length in [0,1,247,248,255]:
            reply=packet(length)
            value=p.frame(reply+b'\xff'*20)
            self.assertEqual(value['raw_hex'],reply.hex())
            self.assertEqual(value['frame_bytes'],9+length)
            self.assertFalse(value['payload_decoded'])
        with self.assertRaises(OSError) as caught:p.frame(packet(255)[:256])
        self.assertEqual(caught.exception.errno,errno.EMSGSIZE)

    def test_bad_frame_bounds_and_magic_stay_unavailable(self):
        for reply,code in [(b'',errno.EMSGSIZE),(b'\x5a\xa5'+b'\x00'*4,errno.EMSGSIZE),
                           (b'\x5a\xa5'+b'\x00'*5,errno.EMSGSIZE),(b'\x00'*9,errno.ENODATA),
                           (b'\x00'*1025,errno.EOVERFLOW),(b'\xfe\xff\xff\xff',errno.EOPNOTSUPP),('not bytes',errno.EPROTO)]:
            with self.subTest(code=code),self.assertRaises(OSError) as caught:p.frame(reply)
            self.assertEqual(caught.exception.errno,code)

    def test_old_versions_query_common_registers_and_skip_bu(self):
        values=words(common=(0x12345678,0xffffffff))
        result,scalar,buffer=read(values,[packet(),b'',b''])
        self.assertEqual([call.args[0] for call in scalar.call_args_list],[0xe0,0x4e1,0xffe3,0xe3,0x1e3])
        self.assertEqual(result['register'],['0x12345678','0xffffffff'])
        self.assertFalse(result['BU_register_applicable']);self.assertEqual(result['BU_register'],[])
        self.assertIsNone(result['M_date']);self.assertEqual(result['M_date_raw'],0xffffffff)
        self.assertEqual(result['event'][0]['raw_hex'],packet().hex())
        self.assertEqual(buffer.call_count,3)

    def test_newer_versions_query_bu_count_and_its_separate_selectors(self):
        result,scalar,buffer=read(words(version=8,common=(17,),bu=(23,42)),[b'',b''])
        self.assertEqual([call.args[0] for call in scalar.call_args_list],[0xe0,0x4e1,0xffe3,0xe3,0xffe7,0xe7,0x1e7])
        self.assertEqual(result['BU_register'],['0x00000017','0x0000002a'])
        self.assertTrue(result['BU_register_applicable']);self.assertEqual(result['BU_register_count'],2)

    def test_original_two_consecutive_unusable_replies_reset_after_a_good_packet(self):
        result,scalar,buffer=read(words(),[b'',packet(),b'',packet(1),b'',b''])
        self.assertEqual(len(result['event']),2);self.assertEqual(buffer.call_count,6)
        state=result['event_stream'];self.assertEqual(state['attempts'],6)
        self.assertEqual(state['termination'],'two_unusable_replies')
        self.assertFalse(state['complete_history_proven']);self.assertFalse(state['truncated'])

    def test_transport_errors_are_preserved_with_partial_frames(self):
        result,scalar,buffer=read(words(),[packet(),OSError(errno.EIO,'Read failed'),OSError(errno.EBUSY,'Device busy')])
        state=result['event_stream'];self.assertTrue(state['available'])
        self.assertEqual([r['errno'] for r in state['failures']],[errno.EIO,errno.EBUSY])
        self.assertFalse(state['complete_history_proven']);self.assertEqual(len(result['event']),1)

    def test_event_budget_is_explicit_and_never_discards_a_fetched_valid_frame(self):
        result,scalar,buffer=read(words(),[packet(),packet(1),packet(2)],max_events=2)
        self.assertEqual(buffer.call_count,2);self.assertEqual(len(result['event']),2)
        self.assertTrue(result['event_stream']['truncated'])
        self.assertEqual(result['event_stream']['termination'],'record_limit')

    def test_changed_version_fails_before_other_scalar_or_buffer_reads(self):
        scalar=mock.Mock(return_value=9);buffer=mock.Mock()
        with self.assertRaises(OSError) as caught:p.read_table(scalar,buffer,8)
        self.assertEqual(caught.exception.errno,errno.EAGAIN)
        scalar.assert_called_once_with(0xe0);buffer.assert_not_called()

    def test_count_sentinels_and_excess_bounds_are_not_empty_or_partial_lists(self):
        for version,selector in [(7,0xffe3),(8,0xffe7)]:
            for count,code in [(0xffffffff,errno.ENODATA),(65,errno.EOVERFLOW),(True,errno.EPROTO)]:
                values=words(version);values[selector]=count;buffer=mock.Mock()
                with self.subTest(selector=selector,count=count),self.assertRaises(OSError) as caught:
                    p.read_table(lambda i:values[i],buffer,version)
                self.assertEqual(caught.exception.errno,code);buffer.assert_not_called()

    def test_scalar_transport_failure_aborts_without_fabricating_register_data(self):
        values=words(common=(10,))
        def scalar(selector):
            if selector==0xe3:raise OSError(errno.EIO,'Register unavailable')
            return values[selector]
        buffer=mock.Mock()
        with self.assertRaises(OSError) as caught:p.read_table(scalar,buffer,7)
        self.assertEqual(caught.exception.errno,errno.EIO);buffer.assert_not_called()

    def test_manufacture_timestamp_uses_local_calendar_date_and_distinguishes_sentinel(self):
        for zone,expected in [('UTC','2024-01-01'),('America/Los_Angeles','2023-12-31')]:
            try:
                with mock.patch.dict(os.environ,{'TZ':zone}):
                    time.tzset();result,scalar,buffer=read(words(date=1704067200),[b'',b''])
                    self.assertEqual(result['M_date'],expected)
            finally:time.tzset()

    def test_unknown_arguments_fail_before_transport_access(self):
        scalar=mock.Mock();buffer=mock.Mock()
        for version,count in [(True,1),(-1,1),(0xffffffff,1),(7,0),(7,65),(7,True)]:
            with self.subTest(version=version,count=count),self.assertRaises(ValueError):p.read_table(scalar,buffer,version,count)
        scalar.assert_not_called();buffer.assert_not_called()

    def test_privileged_adapter_uses_only_original_fixed_scalar_and_e5_recipes(self):
        values=words(common=(1,));replies=iter([packet(),b'',b''])
        def rpc(op,index,apply=False):
            self.assertIs(apply,True)
            if op==11:return {'value':values[index]}
            self.assertEqual((op,index),(13,0xe5));return {'data_hex':next(replies).hex()}
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(p,'Path',return_value=Path(temp)),mock.patch.object(p.os,'geteuid',return_value=0),mock.patch.object(p.native_oem,'rpc',side_effect=rpc) as calls:
            result=p.collect(7)
        self.assertEqual(result['version'],7)
        self.assertTrue(all(c.args[0] in (11,13) and c.kwargs=={'apply':True} for c in calls.call_args_list))

    def test_unprivileged_collection_never_opens_a_lock_or_queries_firmware(self):
        with mock.patch.object(p.os,'geteuid',return_value=1000),mock.patch.object(p.os,'open',side_effect=AssertionError('Unexpected open')),mock.patch.object(p.native_oem,'rpc') as rpc:
            with self.assertRaises(PermissionError) as caught:p.collect(7)
        self.assertEqual(caught.exception.errno,errno.EACCES);rpc.assert_not_called()
