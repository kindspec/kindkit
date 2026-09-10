#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A JSON Schema (draft 2020-12) evaluator, in the standard library only.

This exists so that `case-tree/expect.schema.json` can be checked against a
tree without the kit taking a dependency. It implements a subset of the draft,
and -- this is the whole point of it being written rather than vendored -- it
**refuses a schema keyword it does not implement** instead of ignoring one.

That refusal is the §2.2 rule applied to the validator itself. Every general
JSON Schema implementation is required by the specification to ignore unknown
keywords, which is correct for interoperability and catastrophic here: a
constraint the evaluator has not heard of would be silently dropped, and the
tree would keep reporting a pass over something nobody was checking. A subset
that says "I cannot check this" is honest; a subset that says "valid" is not.

Deliberate limitations, stated rather than hidden:

* `$ref` resolves only within the document (`#`, `#/$defs/name`). There is no
  remote resolution and no `$dynamicRef`. A case-body schema is applied
  alongside the envelope rather than `$ref`-ing it, so nothing needs it.
* `pattern` and `patternProperties` are compiled with Python `re`, not
  ECMA-262. The two agree on the character classes and anchors a case tree
  uses; they diverge on constructs no such schema has needed.
* `format` is not implemented, and is therefore rejected rather than ignored.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: Keywords that constrain an instance. Anything here is evaluated.
_APPLICATORS = frozenset(
    {
        "type",
        "enum",
        "const",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "properties",
        "patternProperties",
        "additionalProperties",
        "propertyNames",
        "required",
        "dependentRequired",
        "minProperties",
        "maxProperties",
        "prefixItems",
        "items",
        "contains",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "$ref",
    }
)

#: Keywords that carry no assertion. Ignoring one of these cannot drop a check.
_ANNOTATIONS = frozenset(
    {
        "$schema",
        "$id",
        "$anchor",
        "$comment",
        "$defs",
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
    }
)

_KNOWN = _APPLICATORS | _ANNOTATIONS


class SchemaError(Exception):
    """The schema cannot be evaluated, so no verdict about the instance exists.

    Distinct from an invalid instance on purpose: one is a finding about the
    data, the other is the absence of a finding at all.
    """


def _is_number(value: Any) -> bool:
    # `True` is an `int` in Python and is not a number in JSON.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    # 2020-12: a float with zero fractional part IS an integer.
    return isinstance(value, float) and value.is_integer()


_TYPE_CHECKS = {
    "null": lambda v: v is None,
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": _is_number,
    "integer": _is_integer,
}


def _canonical(value: Any) -> str:
    """A stable text form, so `const`/`enum`/`uniqueItems` compare structurally."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _equal(a: Any, b: Any) -> bool:
    # `1 == True` in Python and `1 == true` is false in JSON; canonical text
    # keeps the two apart, and compares objects and arrays by value.
    return _canonical(a) == _canonical(b)


def _compile(pattern: str, where: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise SchemaError(f"{where}: uncompilable pattern {pattern!r}: {exc}") from exc


class Validator:
    """Evaluates one schema document against instances."""

    def __init__(self, schema: Any, name: str = "<schema>") -> None:
        self.name = name
        self.root = schema
        self._check_usable(schema, "#")

    # -- schema-side checks: run once, up front, so an unusable schema is
    # -- never mistaken for a valid instance.

    def _check_usable(self, schema: Any, at: str) -> None:
        if isinstance(schema, bool):
            return
        if not isinstance(schema, dict):
            raise SchemaError(f"{self.name}{at}: a schema must be an object or a boolean")
        unknown = sorted(set(schema) - _KNOWN)
        if unknown:
            raise SchemaError(
                f"{self.name}{at}: unimplemented schema keyword(s) {unknown}. "
                "This evaluator refuses what it cannot check rather than ignoring it."
            )
        for key in ("pattern",):
            if key in schema:
                _compile(schema[key], f"{self.name}{at}/{key}")
        for key in ("properties", "patternProperties", "$defs", "dependentRequired"):
            sub = schema.get(key)
            if sub is not None and not isinstance(sub, dict):
                raise SchemaError(f"{self.name}{at}/{key}: must be an object")
        for name, sub in (schema.get("patternProperties") or {}).items():
            _compile(name, f"{self.name}{at}/patternProperties/{name}")
            self._check_usable(sub, f"{at}/patternProperties/{name}")
        for key in ("properties", "$defs"):
            for name, sub in (schema.get(key) or {}).items():
                self._check_usable(sub, f"{at}/{key}/{name}")
        for key in (
            "not",
            "if",
            "then",
            "else",
            "items",
            "contains",
            "additionalProperties",
            "propertyNames",
        ):
            if key in schema:
                self._check_usable(schema[key], f"{at}/{key}")
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            entries = schema.get(key)
            if entries is None:
                continue
            if not isinstance(entries, list) or not entries:
                raise SchemaError(f"{self.name}{at}/{key}: must be a non-empty array")
            for index, sub in enumerate(entries):
                self._check_usable(sub, f"{at}/{key}/{index}")
        if "$ref" in schema:
            self._resolve(schema["$ref"], at)

    def _resolve(self, ref: Any, at: str) -> Any:
        if not isinstance(ref, str) or not ref.startswith("#"):
            raise SchemaError(
                f"{self.name}{at}/$ref: only same-document refs are supported, got {ref!r}"
            )
        target: Any = self.root
        for token in ref.lstrip("#").strip("/").split("/"):
            if not token:
                continue
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or token not in target:
                raise SchemaError(f"{self.name}{at}/$ref: cannot resolve {ref!r}")
            target = target[token]
        return target

    # -- instance-side evaluation

    def errors(self, instance: Any, path: str = "") -> list[str]:
        """Every way ``instance`` violates the schema. Empty means valid."""
        return self._errors(instance, self.root, path or "$")

    def is_valid(self, instance: Any) -> bool:
        return not self.errors(instance)

    def _errors(self, value: Any, schema: Any, path: str) -> list[str]:  # noqa: C901
        if schema is True:
            return []
        if schema is False:
            return [f"{path}: no value is valid here"]

        out: list[str] = []

        if "$ref" in schema:
            out += self._errors(value, self._resolve(schema["$ref"], path), path)

        if "type" in schema:
            wanted = schema["type"]
            names = [wanted] if isinstance(wanted, str) else list(wanted)
            for name in names:
                if name not in _TYPE_CHECKS:
                    raise SchemaError(f"{self.name}: unknown type {name!r}")
            if not any(_TYPE_CHECKS[name](value) for name in names):
                out.append(f"{path}: expected type {'|'.join(names)}, got {_typename(value)}")

        if "const" in schema and not _equal(value, schema["const"]):
            out.append(f"{path}: expected {_canonical(schema['const'])}, got {_canonical(value)}")

        if "enum" in schema and not any(_equal(value, item) for item in schema["enum"]):
            allowed = ", ".join(_canonical(item) for item in schema["enum"])
            out.append(f"{path}: {_canonical(value)} is not one of [{allowed}]")

        out += self._combinators(value, schema, path)
        if isinstance(value, str):
            out += self._string(value, schema, path)
        if _is_number(value):
            out += self._number(value, schema, path)
        if isinstance(value, list):
            out += self._array(value, schema, path)
        if isinstance(value, dict):
            out += self._object(value, schema, path)
        return out

    def _combinators(self, value: Any, schema: dict, path: str) -> list[str]:
        out: list[str] = []
        for sub in schema.get("allOf", ()):
            out += self._errors(value, sub, path)
        if "anyOf" in schema and not any(
            not self._errors(value, sub, path) for sub in schema["anyOf"]
        ):
            out.append(f"{path}: matched none of the {len(schema['anyOf'])} anyOf branches")
        if "oneOf" in schema:
            matched = [
                i for i, sub in enumerate(schema["oneOf"]) if not self._errors(value, sub, path)
            ]
            if len(matched) != 1:
                out.append(
                    f"{path}: matched {len(matched)} of the {len(schema['oneOf'])} "
                    "oneOf branches, expected exactly 1"
                )
        if "not" in schema and not self._errors(value, schema["not"], path):
            out.append(f"{path}: must not match the 'not' schema, but does")
        if "if" in schema:
            branch = "then" if not self._errors(value, schema["if"], path) else "else"
            if branch in schema:
                out += self._errors(value, schema[branch], path)
        return out

    def _string(self, value: str, schema: dict, path: str) -> list[str]:
        out: list[str] = []
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: {value!r} does not match pattern {schema['pattern']!r}")
        return out

    def _number(self, value: Any, schema: dict, path: str) -> list[str]:
        out: list[str] = []
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: {value} is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: {value} is above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            out.append(f"{path}: {value} is not above {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            out.append(f"{path}: {value} is not below {schema['exclusiveMaximum']}")
        if "multipleOf" in schema:
            quotient = value / schema["multipleOf"]
            if not float(quotient).is_integer():
                out.append(f"{path}: {value} is not a multiple of {schema['multipleOf']}")
        return out

    def _array(self, value: list, schema: dict, path: str) -> list[str]:
        out: list[str] = []
        prefix = schema.get("prefixItems") or []
        for index, item in enumerate(value):
            if index < len(prefix):
                out += self._errors(item, prefix[index], f"{path}[{index}]")
            elif "items" in schema:
                out += self._errors(item, schema["items"], f"{path}[{index}]")
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{path}: has {len(value)} items, minItems is {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{path}: has {len(value)} items, maxItems is {schema['maxItems']}")
        if schema.get("uniqueItems") and len({_canonical(item) for item in value}) != len(value):
            out.append(f"{path}: items are not unique")
        if "contains" in schema and not any(
            not self._errors(item, schema["contains"], path) for item in value
        ):
            out.append(f"{path}: no item matches 'contains'")
        return out

    def _object(self, value: dict, schema: dict, path: str) -> list[str]:
        out: list[str] = []
        for name in schema.get("required", ()):
            if name not in value:
                out.append(f"{path}: missing required property {name!r}")
        for name, needed in (schema.get("dependentRequired") or {}).items():
            if name in value:
                for other in needed:
                    if other not in value:
                        out.append(f"{path}: {name!r} requires {other!r}")
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            out.append(
                f"{path}: has {len(value)} properties, minProperties is {schema['minProperties']}"
            )
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            out.append(
                f"{path}: has {len(value)} properties, maxProperties is {schema['maxProperties']}"
            )

        properties = schema.get("properties") or {}
        patterns = schema.get("patternProperties") or {}
        for name, item in value.items():
            where = f"{path}.{name}"
            matched = False
            if name in properties:
                out += self._errors(item, properties[name], where)
                matched = True
            for pattern, sub in patterns.items():
                if re.search(pattern, name):
                    out += self._errors(item, sub, where)
                    matched = True
            if not matched and "additionalProperties" in schema:
                out += self._errors(item, schema["additionalProperties"], where)
            if "propertyNames" in schema:
                out += self._errors(name, schema["propertyNames"], f"{path}: key {name!r}")
        return out


def _typename(value: Any) -> str:
    for name, check in _TYPE_CHECKS.items():
        if name != "integer" and check(value):
            return name
    return type(value).__name__


def load(path: str) -> Validator:
    """Read a schema document from disk and prepare it for evaluation."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError(f"cannot read schema {path!r}: {exc}") from exc
    return Validator(document, name=path)
