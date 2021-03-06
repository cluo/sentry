# -*- coding: utf-8 -*-

from __future__ import absolute_import

import mock

from sentry.buffer.redis import RedisBuffer
from sentry.models import Group, Project
from sentry.testutils import TestCase


class RedisBufferTest(TestCase):
    def setUp(self):
        self.buf = RedisBuffer(hosts={
            0: {'db': 9}
        })

    def test_default_host_is_local(self):
        buf = RedisBuffer()
        self.assertEquals(len(buf.conn.hosts), 1)
        self.assertEquals(buf.conn.hosts[0].host, 'localhost')

    def test_coerce_val_handles_foreignkeys(self):
        assert self.buf._coerce_val(Project(id=1)) == '1'

    def test_coerce_val_handles_unicode(self):
        assert self.buf._coerce_val(u'\u201d') == '”'

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.redis.process_incr')
    def test_process_pending(self, process_incr):
        self.buf.conn.zadd('b:p', 1, 'foo')
        self.buf.conn.zadd('b:p', 2, 'bar')
        self.buf.process_pending()
        assert len(process_incr.apply_async.mock_calls) == 2
        process_incr.apply_async.assert_any_call(kwargs={'key': 'foo'})
        process_incr.apply_async.assert_any_call(kwargs={'key': 'bar'})
        assert self.buf.conn.zrange('b:p', 0, -1) == []

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.base.Buffer.process')
    def test_process_does_bubble_up(self, process):
        self.buf.conn.hmset('foo', {
            'e+foo': "S'bar'\np1\n.",
            'f': "(dp1\nS'pk'\np2\nI1\ns.",
            'i+times_seen': '2',
            'm': 'sentry.models.Group',
        })
        columns = {'times_seen': 2}
        filters = {'pk': 1}
        extra = {'foo': 'bar'}
        self.buf.process('foo')
        process.assert_called_once_with(Group, columns, filters, extra)

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.redis.process_incr', mock.Mock())
    def test_incr_saves_to_redis(self):
        model = mock.Mock()
        model.__name__ = 'Mock'
        columns = {'times_seen': 1}
        filters = {'pk': 1}
        self.buf.incr(model, columns, filters, extra={'foo': 'bar'})
        result = self.buf.conn.hgetall('foo')
        assert result == {
            'e+foo': "S'bar'\np1\n.",
            'f': "(dp1\nS'pk'\np2\nI1\ns.",
            'i+times_seen': '1',
            'm': 'mock.Mock',
        }
        pending = self.buf.conn.zrange('b:p', 0, -1)
        assert pending == ['foo']
        self.buf.incr(model, columns, filters, extra={'foo': 'bar'})
        result = self.buf.conn.hgetall('foo')
        assert result == {
            'e+foo': "S'bar'\np1\n.",
            'f': "(dp1\nS'pk'\np2\nI1\ns.",
            'i+times_seen': '2',
            'm': 'mock.Mock',
        }
        pending = self.buf.conn.zrange('b:p', 0, -1)
        assert pending == ['foo']
