import pytest

from jinja2 import DictLoader
from jinja2 import Environment
from jinja2.bccache import Bucket
from jinja2.bccache import BytecodeCache
from jinja2.bccache import FileSystemBytecodeCache
from jinja2.bccache import MemcachedBytecodeCache
from jinja2.exceptions import TemplateNotFound


@pytest.fixture
def env(package_loader, tmp_path):
    bytecode_cache = FileSystemBytecodeCache(str(tmp_path))
    return Environment(loader=package_loader, bytecode_cache=bytecode_cache)


class TestByteCodeCache:
    def test_simple(self, env):
        tmpl = env.get_template("test.html")
        assert tmpl.render().strip() == "BAR"
        pytest.raises(TemplateNotFound, env.get_template, "missing.html")

    def test_async_hooks_are_used(self, run_async_fn):
        class AsyncOnlyBytecodeCache(BytecodeCache):
            def __init__(self) -> None:
                self.loaded = 0
                self.dumped = 0
                self._store: dict[str, bytes] = {}

            def load_bytecode(self, bucket: Bucket) -> None:  # pragma: no cover
                raise AssertionError("sync load_bytecode should not be called")

            def dump_bytecode(self, bucket: Bucket) -> None:  # pragma: no cover
                raise AssertionError("sync dump_bytecode should not be called")

            async def load_bytecode_async(self, bucket: Bucket) -> None:
                self.loaded += 1
                data = self._store.get(bucket.key)

                if data is not None:
                    bucket.bytecode_from_string(data)

            async def dump_bytecode_async(self, bucket: Bucket) -> None:
                self.dumped += 1
                self._store[bucket.key] = bucket.bytecode_to_string()

        cache = AsyncOnlyBytecodeCache()
        env = Environment(
            loader=DictLoader({"a.html": "{{ 42 }}"}),
            bytecode_cache=cache,
            # Disable the template cache so we exercise bytecode cache more than once.
            cache_size=0,
        )

        async def load() -> str:
            tmpl = await env.get_template_async("a.html")
            return tmpl.render()

        assert run_async_fn(load) == "42"
        assert cache.loaded == 1
        assert cache.dumped == 1

        # Second load should come from bytecode cache, so it should not dump again.
        assert run_async_fn(load) == "42"
        assert cache.loaded == 2
        assert cache.dumped == 1


class MockMemcached:
    class Error(Exception):
        pass

    key = None
    value = None
    timeout = None

    def get(self, key):
        return self.value

    def set(self, key, value, timeout=None):
        self.key = key
        self.value = value
        self.timeout = timeout

    def get_side_effect(self, key):
        raise self.Error()

    def set_side_effect(self, *args):
        raise self.Error()


class TestMemcachedBytecodeCache:
    def test_dump_load(self):
        memcached = MockMemcached()
        m = MemcachedBytecodeCache(memcached)

        b = Bucket(None, "key", "")
        b.code = "code"
        m.dump_bytecode(b)
        assert memcached.key == "jinja2/bytecode/key"

        b = Bucket(None, "key", "")
        m.load_bytecode(b)
        assert b.code == "code"

    def test_exception(self):
        memcached = MockMemcached()
        memcached.get = memcached.get_side_effect
        memcached.set = memcached.set_side_effect
        m = MemcachedBytecodeCache(memcached)
        b = Bucket(None, "key", "")
        b.code = "code"

        m.dump_bytecode(b)
        m.load_bytecode(b)

        m.ignore_memcache_errors = False

        with pytest.raises(MockMemcached.Error):
            m.dump_bytecode(b)

        with pytest.raises(MockMemcached.Error):
            m.load_bytecode(b)
