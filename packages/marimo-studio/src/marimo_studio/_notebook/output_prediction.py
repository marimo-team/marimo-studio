"""Bound static output prediction for notebook-populated starters."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Protocol, cast

_CallableNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


@dataclass(frozen=True)
class _DeferredCall:
    function: _CallableNode
    call: ast.Call
    bindings: dict[str, _BindingNode | None]


@dataclass(frozen=True)
class _DeferredGenerator:
    expression: ast.GeneratorExp
    first_iterable: _BindingNode | None


@dataclass(frozen=True)
class _DeferredAdapter:
    kind: str
    callback: _BindingNode | None
    sources: tuple[_BindingNode | None, ...]


_DeferredNode = _DeferredGenerator | _DeferredCall | _DeferredAdapter


@dataclass(frozen=True)
class _AlternativeBinding:
    values: tuple[_BindingNode, ...]
    unknown: bool = False


@dataclass(frozen=True)
class _MarimoBinding:
    pass


@dataclass(frozen=True)
class _MarimoOperation:
    name: str


@dataclass(frozen=True)
class _MarimoOutputBinding:
    pass


_MARIMO = _MarimoBinding()
_MARIMO_OUTPUT = _MarimoOutputBinding()
_MARIMO_SQL = _MarimoOperation("sql")
_MARIMO_APPEND = _MarimoOperation("append")
_MARIMO_REPLACE = _MarimoOperation("replace")
_MARIMO_REPLACE_AT_INDEX = _MarimoOperation("replace_at_index")
_POSSIBLE_OUTPUT_WORK_BUDGET = 20_000
_BindingNode = (
    _CallableNode
    | _DeferredNode
    | _AlternativeBinding
    | _MarimoBinding
    | _MarimoOutputBinding
    | _MarimoOperation
)


class _TryNode(Protocol):
    body: list[ast.stmt]
    handlers: list[ast.ExceptHandler]
    orelse: list[ast.stmt]
    finalbody: list[ast.stmt]


class _SymbolicWorkLimit(RuntimeError):
    pass


class _PossibleOutputFound(RuntimeError):
    pass


class _LocalBindingVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    def visit_ListComp(self, node: ast.ListComp) -> None:
        del node

    def visit_SetComp(self, node: ast.SetComp) -> None:
        del node

    def visit_DictComp(self, node: ast.DictComp) -> None:
        del node

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        del node

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocals.update(node.names)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)


class _PossibleOutputVisitor(ast.NodeVisitor):
    _EAGER_ITERABLE_CALLS = frozenset(
        {
            "all",
            "any",
            "dict",
            "frozenset",
            "list",
            "max",
            "min",
            "set",
            "sorted",
            "sum",
            "tuple",
        }
    )

    def __init__(self, work_budget: int | None = None) -> None:
        self._work_remaining = (
            _POSSIBLE_OUTPUT_WORK_BUDGET if work_budget is None else work_budget
        )
        self._active_functions: set[int] = set()
        self._active_deferred: set[int] = set()
        self._consume_return_values: list[bool] = []
        self._return_bindings: list[list[_BindingNode | None]] = []
        self._deferred_call_results: set[int] = set()
        self._loop_depth = 0
        self._try_snapshots: list[tuple[int, list[dict[str, _BindingNode | None]]]] = []
        self._default_bindings: dict[
            int,
            dict[str, _BindingNode | None],
        ] = {}
        self._generator_cache: dict[int, bool] = {}
        self._local_name_cache: dict[int, frozenset[str]] = {}
        self._function_node_counts: dict[int, int] = {}
        self._termination_cache: dict[int, bool] = {}
        self._loop_control_cache: dict[int, bool] = {}
        self._match_exhaustive_cache: dict[int, bool] = {}
        self._irrefutable_pattern_cache: dict[int, bool] = {}
        self._output_false_cache: dict[int, bool] = {}
        self._scopes: list[dict[str, _BindingNode | None]] = [{}]

    def _charge(self, amount: int = 1) -> None:
        self._work_remaining -= max(1, amount)
        if self._work_remaining < 0:
            raise _SymbolicWorkLimit

    def _copy_scope(
        self,
        scope: dict[str, _BindingNode | None],
    ) -> dict[str, _BindingNode | None]:
        self._charge(len(scope))
        return dict(scope)

    def visit(self, node: ast.AST) -> None:
        self._charge()
        super().visit(node)

    def _is_marimo(self, node: ast.expr) -> bool:
        return any(
            isinstance(value, _MarimoBinding)
            for value in self._binding_values(self._binding(node))
        )

    def _is_marimo_output(self, node: ast.expr) -> bool:
        return any(
            isinstance(value, _MarimoOutputBinding)
            for value in self._binding_values(self._binding(node))
        )

    def _marimo_operations(self, node: ast.expr) -> tuple[_MarimoOperation, ...]:
        return tuple(
            value
            for value in self._binding_values(self._binding(node))
            if isinstance(value, _MarimoOperation)
        )

    def _output_is_false(self, node: ast.Call) -> bool:
        identity = id(node)
        if identity in self._output_false_cache:
            return self._output_false_cache[identity]
        self._charge(len(node.keywords))
        value = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "output"),
            None,
        )
        result = isinstance(value, ast.Constant) and value.value is False
        self._output_false_cache[identity] = result
        return result

    def _lookup(self, name: str) -> tuple[bool, _BindingNode | None]:
        self._charge(len(self._scopes))
        for scope in reversed(self._scopes):
            if name in scope:
                return True, scope[name]
        return False, None

    def _bound(self, name: str) -> _BindingNode | None:
        _found, value = self._lookup(name)
        return value

    def _reference(self, name: str) -> _BindingNode | None:
        found, value = self._lookup(name)
        return value if found else (_MARIMO if name in {"marimo", "mo"} else None)

    def _functions(self, name: str) -> tuple[_CallableNode, ...]:
        value = self._bound(name)
        return tuple(
            item
            for item in self._binding_values(value)
            if isinstance(item, _CallableNode)
        )

    def _deferred(self, name: str) -> _BindingNode | None:
        value = self._bound(name)
        return value if self._contains_deferred(value) else None

    def _binding_values(
        self,
        value: _BindingNode | None,
    ) -> tuple[_BindingNode, ...]:
        if value is None:
            return ()
        if isinstance(value, _AlternativeBinding):
            self._charge(len(value.values))
            return value.values
        return (value,)

    def _contains_deferred(self, value: _BindingNode | None) -> bool:
        return any(
            isinstance(item, (_DeferredGenerator, _DeferredCall, _DeferredAdapter))
            for item in self._binding_values(value)
        )

    def _is_bound(self, name: str) -> bool:
        found, _value = self._lookup(name)
        return found

    def _binding(self, node: ast.expr) -> _BindingNode | None:
        self._charge()
        if isinstance(node, ast.Lambda):
            return node
        if isinstance(node, ast.GeneratorExp):
            first_iterable: _BindingNode | None = None
            if node.generators:
                value = self._binding(node.generators[0].iter)
                if self._contains_deferred(value):
                    first_iterable = value
            return _DeferredGenerator(node, first_iterable)
        if isinstance(node, ast.Name):
            return self._reference(node.id)
        if isinstance(node, ast.Attribute):
            if node.attr == "sql" and self._is_marimo(node.value):
                return _MARIMO_SQL
            if node.attr == "output" and self._is_marimo(node.value):
                return _MARIMO_OUTPUT
            if self._is_marimo_output(node.value):
                return {
                    "append": _MARIMO_APPEND,
                    "replace": _MARIMO_REPLACE,
                    "replace_at_index": _MARIMO_REPLACE_AT_INDEX,
                }.get(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Lambda):
            bindings = self._call_bindings(node.func, node)
            self._scopes.append(self._copy_scope(bindings))
            try:
                result = self._binding(node.func.body)
            finally:
                self._scopes.pop()
            if self._contains_deferred(result):
                return _DeferredCall(node.func, node, bindings)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if (
                node.func.id == "iter"
                and not self._is_bound("iter")
                and len(node.args) == 1
                and not node.keywords
            ):
                value = self._binding(node.args[0])
                if self._contains_deferred(value):
                    return value
            if (
                node.func.id == "enumerate"
                and not self._is_bound("enumerate")
                and node.args
                and not isinstance(node.args[0], ast.Starred)
            ):
                value = self._binding(node.args[0])
                if self._contains_deferred(value):
                    return value
            if (
                node.func.id == "map"
                and not self._is_bound("map")
                and len(node.args) >= 2
                and not any(isinstance(argument, ast.Starred) for argument in node.args)
            ):
                callback = self._binding(node.args[0])
                sources = tuple(self._binding(argument) for argument in node.args[1:])
                if callback is not None or any(
                    self._contains_deferred(source) for source in sources
                ):
                    return _DeferredAdapter("map", callback, sources)
            if (
                node.func.id == "filter"
                and not self._is_bound("filter")
                and len(node.args) == 2
                and not any(isinstance(argument, ast.Starred) for argument in node.args)
            ):
                callback = self._binding(node.args[0])
                source = self._binding(node.args[1])
                if callback is not None or self._contains_deferred(source):
                    return _DeferredAdapter("filter", callback, (source,))
            if (
                node.func.id == "zip"
                and not self._is_bound("zip")
                and not any(isinstance(argument, ast.Starred) for argument in node.args)
            ):
                sources = tuple(self._binding(argument) for argument in node.args)
                if any(self._contains_deferred(source) for source in sources):
                    return _DeferredAdapter("zip", None, sources)
            deferred_calls: list[_DeferredCall] = []
            for function in self._functions(node.func.id):
                if (
                    isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and self._is_generator(function)
                ) or id(node) in self._deferred_call_results:
                    deferred_calls.append(
                        _DeferredCall(
                            function,
                            node,
                            self._call_bindings(function, node),
                        )
                    )
            if len(deferred_calls) == 1:
                return deferred_calls[0]
            if deferred_calls:
                return _AlternativeBinding(tuple(deferred_calls))
        return None

    def _is_generator(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        identity = id(node)
        cached = self._generator_cache.get(identity)
        if cached is not None:
            return cached
        self._charge(self._function_node_count(node))

        class YieldDetector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.found = False

            def visit_Yield(self, node: ast.Yield) -> None:
                del node
                self.found = True

            def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
                del node
                self.found = True

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                del node

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                del node

            def visit_Lambda(self, node: ast.Lambda) -> None:
                del node

        detector = YieldDetector()
        for statement in node.body:
            detector.visit(statement)
        self._generator_cache[identity] = detector.found
        return detector.found

    def _local_names(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> frozenset[str]:
        identity = id(function)
        cached = self._local_name_cache.get(identity)
        if cached is not None:
            return cached
        self._charge(self._function_node_count(function))
        visitor = _LocalBindingVisitor()
        arguments = function.args
        visitor.names.update(
            argument.arg
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            )
        )
        if arguments.vararg is not None:
            visitor.names.add(arguments.vararg.arg)
        if arguments.kwarg is not None:
            visitor.names.add(arguments.kwarg.arg)
        for statement in function.body:
            visitor.visit(statement)
        names = frozenset(visitor.names - visitor.globals - visitor.nonlocals)
        self._local_name_cache[identity] = names
        return names

    def _function_node_count(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> int:
        identity = id(function)
        count = self._function_node_counts.get(identity)
        if count is None:
            count = sum(1 for _node in ast.walk(function))
            self._function_node_counts[identity] = count
        return count

    def _call_bindings(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
        call: ast.Call,
    ) -> dict[str, _BindingNode | None]:
        arguments = function.args
        bindings: dict[str, _BindingNode | None]
        if isinstance(function, ast.Lambda):
            parameter_names = [
                argument.arg
                for argument in (
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                )
            ]
            if arguments.vararg is not None:
                parameter_names.append(arguments.vararg.arg)
            if arguments.kwarg is not None:
                parameter_names.append(arguments.kwarg.arg)
            self._charge(len(parameter_names))
            bindings = dict.fromkeys(parameter_names)
        else:
            local_names = self._local_names(function)
            self._charge(len(local_names))
            bindings = dict.fromkeys(local_names)
        defaults = self._default_bindings.get(id(function), {})
        self._charge(len(defaults))
        bindings.update(defaults)

        positional = (*arguments.posonlyargs, *arguments.args)
        for parameter, value in zip(positional, call.args, strict=False):
            if not isinstance(value, ast.Starred):
                self._charge()
                bindings[parameter.arg] = self._binding(value)
        for keyword in call.keywords:
            if keyword.arg is not None:
                self._charge()
                bindings[keyword.arg] = self._binding(keyword.value)
        return bindings

    def _execute_function(
        self,
        function: _CallableNode,
        call: ast.Call,
        *,
        consume_result: bool,
        bindings: dict[str, _BindingNode | None] | None = None,
    ) -> bool:
        self._charge()
        identity = id(function)
        generator = isinstance(
            function, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and self._is_generator(function)
        if identity in self._active_functions or (generator and not consume_result):
            return False
        self._active_functions.add(identity)
        selected_bindings = (
            bindings if bindings is not None else self._call_bindings(function, call)
        )
        self._scopes.append(self._copy_scope(selected_bindings))
        self._consume_return_values.append(consume_result and not generator)
        returned: list[_BindingNode | None] = []
        self._return_bindings.append(returned)
        try:
            if isinstance(function, ast.Lambda):
                returned.append(self._binding(function.body))
                if consume_result:
                    self._consume_expression(function.body)
                else:
                    self.visit(function.body)
            else:
                self._visit_statements(function.body)
        finally:
            self._return_bindings.pop()
            self._consume_return_values.pop()
            self._scopes.pop()
            self._active_functions.remove(identity)
        return any(self._contains_deferred(value) for value in returned)

    def _terminates(self, statement: ast.stmt) -> bool:
        identity = id(statement)
        if identity in self._termination_cache:
            return self._termination_cache[identity]
        self._charge()
        result = False
        if isinstance(statement, (ast.Raise, ast.Return)):
            result = True
        elif isinstance(statement, ast.If):
            result = (
                bool(statement.body)
                and bool(statement.orelse)
                and self._sequence_terminates(statement.body)
                and self._sequence_terminates(statement.orelse)
            )
        elif isinstance(statement, ast.Match):
            result = self._match_is_exhaustive(statement) and all(
                self._sequence_terminates(case.body) for case in statement.cases
            )
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            result = self._sequence_terminates(statement.body)
        elif isinstance(statement, ast.Try) or type(statement).__name__ == "TryStar":
            result = self._try_terminates(cast(_TryNode, statement))
        self._termination_cache[identity] = result
        return result

    def _try_terminates(self, node: _TryNode) -> bool:
        if self._sequence_terminates(node.finalbody):
            return True
        body_terminates = self._sequence_terminates(node.body)
        normal_path_terminates = body_terminates or self._sequence_terminates(
            node.orelse
        )
        handlers_terminate = all(
            self._sequence_terminates(handler.body) for handler in node.handlers
        )
        return normal_path_terminates and handlers_terminate

    def _match_is_exhaustive(self, node: ast.Match) -> bool:
        identity = id(node)
        if identity in self._match_exhaustive_cache:
            return self._match_exhaustive_cache[identity]
        self._charge(len(node.cases))
        result = False
        if node.cases:
            final = node.cases[-1]
            result = final.guard is None and self._pattern_is_irrefutable(final.pattern)
        self._match_exhaustive_cache[identity] = result
        return result

    def _pattern_is_irrefutable(self, pattern: ast.pattern) -> bool:
        identity = id(pattern)
        if identity in self._irrefutable_pattern_cache:
            return self._irrefutable_pattern_cache[identity]
        self._charge()
        result = False
        if isinstance(pattern, ast.MatchAs):
            result = pattern.pattern is None or self._pattern_is_irrefutable(
                pattern.pattern
            )
        elif isinstance(pattern, ast.MatchOr):
            self._charge(len(pattern.patterns))
            result = any(
                self._pattern_is_irrefutable(item) for item in pattern.patterns
            )
        self._irrefutable_pattern_cache[identity] = result
        return result

    def _sequence_terminates(self, statements: list[ast.stmt]) -> bool:
        self._charge(len(statements))
        return any(self._terminates(statement) for statement in statements)

    def _controls_loop(self, statement: ast.stmt) -> bool:
        identity = id(statement)
        if identity in self._loop_control_cache:
            return self._loop_control_cache[identity]
        self._charge()
        result = False
        if isinstance(statement, (ast.Break, ast.Continue)):
            result = True
        elif isinstance(statement, ast.If):
            result = (
                bool(statement.body)
                and bool(statement.orelse)
                and self._sequence_controls_loop(statement.body)
                and self._sequence_controls_loop(statement.orelse)
            )
        elif isinstance(statement, ast.Match):
            result = self._match_is_exhaustive(statement) and all(
                self._sequence_controls_loop(case.body) for case in statement.cases
            )
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            result = self._sequence_controls_loop(statement.body)
        elif isinstance(statement, ast.Try) or type(statement).__name__ == "TryStar":
            result = self._try_controls_loop(cast(_TryNode, statement))
        self._loop_control_cache[identity] = result
        return result

    def _try_controls_loop(self, node: _TryNode) -> bool:
        if self._sequence_controls_loop(node.finalbody):
            return True
        if self._sequence_terminates(node.finalbody):
            return False
        body_controls = self._sequence_controls_loop(node.body)
        normal_path_controls = body_controls or self._sequence_controls_loop(
            node.orelse
        )
        handlers_control = all(
            self._sequence_controls_loop(handler.body) for handler in node.handlers
        )
        return normal_path_controls and handlers_control

    def _sequence_controls_loop(self, statements: list[ast.stmt]) -> bool:
        self._charge(len(statements))
        return any(self._controls_loop(statement) for statement in statements)

    def _visit_statements(self, statements: list[ast.stmt]) -> bool:
        for statement in statements:
            self._record_try_snapshot()
            self.visit(statement)
            self._record_try_snapshot()
            if self._terminates(statement) or (
                self._loop_depth and self._controls_loop(statement)
            ):
                return True
        return False

    def _record_try_snapshot(self) -> None:
        if not self._try_snapshots:
            return
        self._charge(len(self._try_snapshots))
        scope_index = len(self._scopes) - 1
        for selected_index, snapshots in self._try_snapshots:
            if selected_index == scope_index:
                snapshots.append(self._copy_scope(self._scopes[-1]))

    def _visit_try_body(
        self,
        statements: list[ast.stmt],
    ) -> tuple[bool, list[dict[str, _BindingNode | None]]]:
        snapshots = [self._copy_scope(self._scopes[-1])]
        self._try_snapshots.append((len(self._scopes) - 1, snapshots))
        try:
            terminated = self._visit_statements(statements)
        finally:
            self._try_snapshots.pop()
        return terminated, snapshots

    def _visit_call(
        self,
        node: ast.Call,
        *,
        await_async: bool,
        consume_result: bool = False,
    ) -> None:
        function = node.func
        sql_call = (
            isinstance(function, ast.Attribute)
            and function.attr == "sql"
            and self._is_marimo(function.value)
            and not self._output_is_false(node)
        )
        output_call = (
            isinstance(function, ast.Attribute)
            and function.attr in {"append", "replace", "replace_at_index"}
            and isinstance(function.value, ast.Attribute)
            and function.value.attr == "output"
            and self._is_marimo(function.value.value)
        )
        if sql_call or output_call:
            raise _PossibleOutputFound
        self.visit(function)
        eager_name = (
            function.id
            if isinstance(function, ast.Name) and not self._is_bound(function.id)
            else None
        )
        for index, argument in enumerate(node.args):
            if isinstance(argument, ast.Starred):
                self._consume_expression(argument.value)
            elif (
                eager_name in self._EAGER_ITERABLE_CALLS
                or (eager_name == "next" and index == 0)
                or (eager_name == "anext" and await_async and index == 0)
                or (eager_name == "enumerate" and consume_result and index == 0)
            ):
                self._consume_expression(argument)
            else:
                self.visit(argument)
        for keyword in node.keywords:
            self.visit(keyword.value)
        operations = self._marimo_operations(function)
        if any(
            operation.name != "sql" or not self._output_is_false(node)
            for operation in operations
        ):
            raise _PossibleOutputFound
        if consume_result and eager_name in {"filter", "map", "zip"}:
            deferred = self._binding(node)
            if isinstance(deferred, _DeferredAdapter):
                self._consume_deferred(deferred)
        if isinstance(function, ast.Lambda):
            deferred_result = self._execute_function(
                function,
                node,
                consume_result=consume_result,
            )
            if deferred_result:
                self._deferred_call_results.add(id(node))
            return
        if not isinstance(function, ast.Name):
            return
        local_functions = self._functions(function.id)
        if not local_functions:
            return
        for local in local_functions:
            if (
                isinstance(local, ast.AsyncFunctionDef)
                and not await_async
                and not (consume_result and self._is_generator(local))
            ):
                continue
            deferred_result = self._execute_function(
                local,
                node,
                consume_result=consume_result,
            )
            if deferred_result:
                self._deferred_call_results.add(id(node))

    def visit_Call(self, node: ast.Call) -> None:
        self._visit_call(node, await_async=False)

    def visit_Await(self, node: ast.Await) -> None:
        if isinstance(node.value, ast.Call):
            self._visit_call(node.value, await_async=True)
            return
        self.visit(node.value)

    def _bind_target(
        self,
        node: ast.expr,
        value: _BindingNode | None = None,
    ) -> None:
        if isinstance(node, ast.Name):
            self._charge()
            self._scopes[-1][node.id] = value
            return
        if isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                self._bind_target(element)
            return
        if isinstance(node, ast.Starred):
            self._bind_target(node.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        value = self._binding(node.value)
        for target in node.targets:
            self._bind_target(target, value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self._bind_target(
            node.target,
            self._binding(node.value) if node.value is not None else None,
        )

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.target)
        self.visit(node.value)
        self._bind_target(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_target(node.target, self._binding(node.value))

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._bind_target(target)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._charge()
            self._scopes[-1][alias.asname or alias.name.split(".", 1)[0]] = (
                _MARIMO if alias.name == "marimo" else None
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self._charge()
                binding = None
                if node.level == 0 and node.module == "marimo":
                    binding = {
                        "output": _MARIMO_OUTPUT,
                        "sql": _MARIMO_SQL,
                    }.get(alias.name)
                self._scopes[-1][alias.asname or alias.name] = binding

    def _capture_defaults(
        self,
        arguments: ast.arguments,
    ) -> dict[str, _BindingNode | None]:
        bindings: dict[str, _BindingNode | None] = {}
        positional = (*arguments.posonlyargs, *arguments.args)
        default_parameters = positional[len(positional) - len(arguments.defaults) :]
        for parameter, value in zip(
            default_parameters,
            arguments.defaults,
            strict=True,
        ):
            self.visit(value)
            bindings[parameter.arg] = self._binding(value)
        for parameter, value in zip(
            arguments.kwonlyargs,
            arguments.kw_defaults,
            strict=True,
        ):
            if value is not None:
                self.visit(value)
                bindings[parameter.arg] = self._binding(value)
        return bindings

    def _visit_function_header(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> dict[str, _BindingNode | None]:
        for decorator in node.decorator_list:
            self.visit(decorator)
        return self._capture_defaults(node.args)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._default_bindings[id(node)] = self._visit_function_header(node)
        self._charge()
        self._scopes[-1][node.name] = node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._default_bindings[id(node)] = self._visit_function_header(node)
        self._charge()
        self._scopes[-1][node.name] = node

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._default_bindings[id(node)] = self._capture_defaults(node.args)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        if node.generators:
            self.visit(node.generators[0].iter)

    def _consume_comprehension(
        self,
        generators: list[ast.comprehension],
        values: tuple[ast.expr, ...],
    ) -> None:
        self._scopes.append({})
        try:
            for generator in generators:
                self._consume_expression(generator.iter)
                self._bind_target(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
            for value in values:
                self.visit(value)
        finally:
            self._scopes.pop()

    def _consume_expression(self, node: ast.expr) -> None:
        if isinstance(node, ast.Name):
            deferred = self._deferred(node.id)
            if deferred is not None:
                self._consume_deferred(deferred)
            return
        if isinstance(node, ast.GeneratorExp):
            self.visit(node)
            deferred = self._binding(node)
            assert isinstance(deferred, _DeferredGenerator)
            self._consume_deferred(deferred)
            return
        if isinstance(node, ast.Call):
            self._visit_call(node, await_async=False, consume_result=True)
            return
        self.visit(node)

    def _consume_deferred(self, node: _BindingNode) -> None:
        self._charge()
        if isinstance(node, _AlternativeBinding):
            for value in self._binding_values(node):
                if self._contains_deferred(value):
                    self._consume_deferred(value)
            return
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Lambda,
                _MarimoBinding,
                _MarimoOutputBinding,
                _MarimoOperation,
            ),
        ):
            return
        identity = id(node)
        if identity in self._active_deferred:
            return
        self._active_deferred.add(identity)
        try:
            if isinstance(node, _DeferredGenerator):
                self._consume_generator(node)
            elif isinstance(node, _DeferredAdapter):
                self._consume_adapter(node)
            else:
                assert isinstance(node, _DeferredCall)
                self._execute_function(
                    node.function,
                    node.call,
                    consume_result=True,
                    bindings=node.bindings,
                )
        finally:
            self._active_deferred.remove(identity)

    def _consume_adapter(self, node: _DeferredAdapter) -> None:
        self._charge(len(node.sources))
        for source in node.sources:
            if self._contains_deferred(source):
                assert source is not None
                self._consume_deferred(source)
        if node.callback is None:
            return
        for callback in self._binding_values(node.callback):
            if isinstance(callback, _MarimoOperation):
                raise _PossibleOutputFound
            elif isinstance(callback, _CallableNode):
                self._charge(len(node.sources))
                call = ast.Call(
                    func=ast.Name(id="callback", ctx=ast.Load()),
                    args=[ast.Constant(None) for _source in node.sources],
                    keywords=[],
                )
                self._execute_function(
                    callback,
                    call,
                    consume_result=False,
                )

    def _consume_generator(self, node: _DeferredGenerator) -> None:
        generators = node.expression.generators
        if not generators:
            return
        self._scopes.append({})
        try:
            first = generators[0]
            if node.first_iterable is not None:
                self._consume_deferred(node.first_iterable)
            self._bind_target(first.target)
            for condition in first.ifs:
                self.visit(condition)
            for generator in generators[1:]:
                self._consume_expression(generator.iter)
                self._bind_target(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
            self.visit(node.expression.elt)
        finally:
            self._scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._consume_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._consume_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._consume_comprehension(node.generators, (node.key, node.value))

    def visit_For(self, node: ast.For) -> None:
        self._consume_expression(node.iter)
        initial = self._copy_scope(self._scopes[-1])
        self._scopes[-1] = self._copy_scope(initial)
        self._bind_target(node.target)
        self._loop_depth += 1
        try:
            self._visit_statements(node.body)
        finally:
            self._loop_depth -= 1
        loop_scope = self._merged_scope([initial, self._copy_scope(self._scopes[-1])])
        self._scopes[-1] = self._copy_scope(loop_scope)
        self._visit_statements(node.orelse)
        self._scopes[-1] = self._merged_scope(
            [loop_scope, self._copy_scope(self._scopes[-1])]
        )

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._consume_expression(node.iter)
        initial = self._copy_scope(self._scopes[-1])
        self._scopes[-1] = self._copy_scope(initial)
        self._bind_target(node.target)
        self._loop_depth += 1
        try:
            self._visit_statements(node.body)
        finally:
            self._loop_depth -= 1
        loop_scope = self._merged_scope([initial, self._copy_scope(self._scopes[-1])])
        self._scopes[-1] = self._copy_scope(loop_scope)
        self._visit_statements(node.orelse)
        self._scopes[-1] = self._merged_scope(
            [loop_scope, self._copy_scope(self._scopes[-1])]
        )

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        initial = self._copy_scope(self._scopes[-1])
        branches: list[dict[str, _BindingNode | None]] = []
        self._scopes[-1] = self._copy_scope(initial)
        if not self._visit_statements(node.body):
            branches.append(self._copy_scope(self._scopes[-1]))
        self._scopes[-1] = self._copy_scope(initial)
        if not node.orelse or not self._visit_statements(node.orelse):
            branches.append(self._copy_scope(self._scopes[-1]))
        self._scopes[-1] = self._merged_scope(branches or [initial])

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        initial = self._copy_scope(self._scopes[-1])
        self._scopes[-1] = self._copy_scope(initial)
        self._loop_depth += 1
        try:
            self._visit_statements(node.body)
        finally:
            self._loop_depth -= 1
        loop_scope = self._merged_scope([initial, self._copy_scope(self._scopes[-1])])
        self._scopes[-1] = self._copy_scope(loop_scope)
        self._visit_statements(node.orelse)
        self._scopes[-1] = self._merged_scope(
            [loop_scope, self._copy_scope(self._scopes[-1])]
        )

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        initial = self._copy_scope(self._scopes[-1])
        branches: list[dict[str, _BindingNode | None]] = []
        for case in node.cases:
            self._scopes[-1] = self._copy_scope(initial)
            self.visit(case.pattern)
            if case.guard is not None:
                self.visit(case.guard)
            if not self._visit_statements(case.body):
                branches.append(self._copy_scope(self._scopes[-1]))
        if not self._match_is_exhaustive(node):
            branches.append(initial)
        self._scopes[-1] = self._merged_scope(branches or [initial])

    def _merged_scope(
        self,
        branches: list[dict[str, _BindingNode | None]],
    ) -> dict[str, _BindingNode | None]:
        self._charge(sum(len(branch) for branch in branches))
        keys = set().union(*(branch.keys() for branch in branches))
        merged: dict[str, _BindingNode | None] = {}
        for key in keys:
            values = [branch.get(key) for branch in branches]
            alternatives: list[_BindingNode] = []
            identities: set[int] = set()
            unknown = any(value is None for value in values)
            for value in values:
                if isinstance(value, _AlternativeBinding):
                    unknown = unknown or value.unknown
                for item in self._binding_values(value):
                    if id(item) not in identities:
                        alternatives.append(item)
                        identities.add(id(item))
            if not alternatives:
                merged[key] = None
            elif len(alternatives) == 1 and not unknown:
                merged[key] = alternatives[0]
            else:
                merged[key] = _AlternativeBinding(tuple(alternatives), unknown)
        return merged

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._charge()
            self._scopes[-1][node.name] = None
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._charge()
            self._scopes[-1][node.name] = None

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self._charge()
            self._scopes[-1][node.rest] = None
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is None:
            return
        if self._return_bindings:
            self._return_bindings[-1].append(self._binding(node.value))
        if self._consume_return_values and self._consume_return_values[-1]:
            self._consume_expression(node.value)
        else:
            self.visit(node.value)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self._consume_expression(node.value)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars)
        self._visit_statements(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._visit_except_handler(node)

    def _visit_except_handler(self, node: ast.ExceptHandler) -> bool:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            self._charge()
            self._scopes[-1][node.name] = None
        return self._visit_statements(node.body)

    def _visit_try(self, node: _TryNode) -> None:
        return_start = len(self._return_bindings[-1]) if self._return_bindings else None
        initial = self._copy_scope(self._scopes[-1])
        self._scopes[-1] = self._copy_scope(initial)
        body_terminated, body_snapshots = self._visit_try_body(node.body)
        body_scope = self._copy_scope(self._scopes[-1])
        branches: list[dict[str, _BindingNode | None]] = []
        finally_branches: list[dict[str, _BindingNode | None]] = []
        if not body_terminated:
            self._scopes[-1] = self._copy_scope(body_scope)
            else_terminated = self._visit_statements(node.orelse)
            finally_branches.append(self._copy_scope(self._scopes[-1]))
            if not else_terminated:
                branches.append(self._copy_scope(self._scopes[-1]))
        else:
            finally_branches.append(body_scope)
        handler_entry = self._merged_scope(body_snapshots)
        for handler in node.handlers:
            self._scopes[-1] = self._copy_scope(handler_entry)
            handler_terminated = self._visit_except_handler(handler)
            finally_branches.append(self._copy_scope(self._scopes[-1]))
            if not handler_terminated:
                branches.append(self._copy_scope(self._scopes[-1]))
        fallthrough_scope = self._merged_scope(branches or [initial])
        self._scopes[-1] = self._merged_scope(finally_branches or [initial])
        finalbody_terminates = self._sequence_terminates(node.finalbody)
        if return_start is not None and finalbody_terminates:
            del self._return_bindings[-1][return_start:]
        self._visit_statements(node.finalbody)
        if branches and not finalbody_terminates:
            return_count = (
                len(self._return_bindings[-1]) if self._return_bindings else None
            )
            self._scopes[-1] = fallthrough_scope
            self._visit_statements(node.finalbody)
            if return_count is not None:
                del self._return_bindings[-1][return_count:]

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_try(node)

    def visit_TryStar(self, node: _TryNode) -> None:
        self._visit_try(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._scopes.append({})
        try:
            self._visit_statements(node.body)
        finally:
            self._scopes.pop()
        self._charge()
        self._scopes[-1][node.name] = None


def may_display_output(module: ast.Module) -> bool:
    """Predict recognized Marimo output calls without executing the cell.

    Tracks local aliases, control flow, calls, and deferred iterables. Exhausting
    the symbolic work budget or recursion depth returns True so starter creation
    retains the cell when analysis reaches its limit.
    """
    visitor = _PossibleOutputVisitor()
    try:
        visitor.visit(module)
    except _PossibleOutputFound:
        return True
    except (_SymbolicWorkLimit, RecursionError):
        return True
    return False
