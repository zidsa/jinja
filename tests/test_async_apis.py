import ast
import inspect
import textwrap

from jinja2 import AsyncEnvironment
from jinja2 import DictLoader
from jinja2 import Environment
from jinja2 import FunctionLoader
from jinja2 import loaders
from jinja2 import TemplateNotFound


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


def _get_func_def(func):
    source = textwrap.dedent(inspect.getsource(func))
    mod = ast.parse(source)
    node = mod.body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return node


def _strip_docstring(body):
    if not body:
        return body

    first = body[0]

    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]

    return body


class _NormalizeAsyncBody(ast.NodeTransformer):
    def __init__(self, attr_rename_map):
        super().__init__()
        self._attr_rename_map = attr_rename_map

    def visit_Await(self, node):  # noqa: N802
        # Await is the main structural difference between sync and async bodies.
        return self.visit(node.value)

    def visit_Attribute(self, node):  # noqa: N802
        node = self.generic_visit(node)

        if node.attr in self._attr_rename_map:
            node.attr = self._attr_rename_map[node.attr]

        return node


def _normalized_body_dump(func, attr_rename_map):
    node = _get_func_def(func)
    body = _strip_docstring(node.body)

    mod = ast.Module(body=body, type_ignores=[])
    mod = _NormalizeAsyncBody(attr_rename_map).visit(mod)
    ast.fix_missing_locations(mod)

    return ast.dump(mod, include_attributes=False)


def test_environment_sync_async_api_parity_static():
    # These async endpoints should be a direct parity layer over the sync ones:
    # - same signature
    # - equivalent implementation after stripping docstrings, erasing "await",
    #   and mapping "*_async" attribute calls to their sync counterpart.
    pairs = [
        ("_load_template", "_load_template_async"),
        ("get_template", "get_template_async"),
        ("select_template", "select_template_async"),
        ("get_or_select_template", "get_or_select_template_async"),
        ("list_templates", "list_templates_async"),
        ("compile_templates", "compile_templates_async"),
    ]

    attr_rename_map = {async_name: sync_name for sync_name, async_name in pairs} | {
        # Loader parity used inside the Environment methods.
        "get_source_async": "get_source",
        "list_templates_async": "list_templates",
        "load_async": "load",
    }

    for sync_name, async_name in pairs:
        sync_func = getattr(Environment, sync_name)
        async_func = getattr(Environment, async_name)

        assert inspect.signature(sync_func) == inspect.signature(async_func)

        assert _normalized_body_dump(
            sync_func, attr_rename_map
        ) == _normalized_body_dump(async_func, attr_rename_map)
