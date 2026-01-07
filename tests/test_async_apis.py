import pytest

from jinja2 import AsyncEnvironment
from jinja2 import DictLoader
from jinja2 import Environment
from jinja2 import FunctionLoader
from jinja2 import TemplateNotFound
from jinja2 import loaders


def test_get_template_async_works_with_sync_loader(run_async_fn):
    env = Environment(loader=DictLoader({"a.html": "A"}))

    async def load() -> str:
        tmpl = await env.get_template_async("a.html")
        return tmpl.render()

    assert run_async_fn(load) == "A"


def test_get_template_async_updates_globals_for_cached_template(run_async_fn):
    env = Environment(loader=DictLoader({"a.html": "{{ foo }}"}), cache_size=-1)

    async def load(value: str) -> str:
        tmpl = await env.get_template_async("a.html", globals={"foo": value})
        return tmpl.render()

    assert run_async_fn(load, "one") == "one"
    # Second load returns cached template, but should update globals.
    assert run_async_fn(load, "two") == "two"


def test_list_templates_async_falls_back_to_sync_loader(run_async_fn):
    env = Environment(loader=DictLoader({"a.html": "A", "b.html": "B"}))

    async def load() -> list[str]:
        return await env.list_templates_async()

    assert run_async_fn(load) == ["a.html", "b.html"]


def test_function_loader_supports_async_callable(run_async_fn):
    async def load_template(name: str) -> str | None:
        if name == "a.html":
            return "A"
        return None

    env = Environment(loader=FunctionLoader(load_template))

    async def load() -> str:
        tmpl = await env.get_template_async("a.html")
        return tmpl.render()

    assert run_async_fn(load) == "A"


def test_async_environment_prefers_get_source_async(run_async_fn):
    class Loader(loaders.BaseLoader):
        def get_source(self, environment, template):  # pragma: no cover
            raise AssertionError("sync get_source should not be called")

        async def get_source_async(self, environment, template):
            if template != "a.html":
                raise TemplateNotFound(template)
            return "A", None, lambda: True

    env = AsyncEnvironment(loader=Loader())

    async def load() -> str:
        # AsyncEnvironment.get_template is the async API.
        tmpl = await env.get_template("a.html")
        return await tmpl.render_async()

    assert run_async_fn(load) == "A"


def test_async_environment_list_templates_uses_async_loader(run_async_fn):
    class Loader(loaders.BaseLoader):
        def list_templates(self):  # pragma: no cover
            raise AssertionError("sync list_templates should not be called")

        async def list_templates_async(self) -> list[str]:
            return ["a.html", "b.html"]

        async def get_source_async(self, environment, template):
            return template, None, lambda: True

    env = AsyncEnvironment(loader=Loader())

    async def load() -> list[str]:
        return await env.list_templates()

    assert run_async_fn(load) == ["a.html", "b.html"]

