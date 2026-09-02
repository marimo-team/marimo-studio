import { noReflectApplyRule } from "../rules/no-reflect-apply.ts";
import { ruleTester } from "./rule-tester.ts";

const error = { messageId: "reflectApply" };

ruleTester.run("anti-slop/no-reflect-apply", noReflectApplyRule, {
  valid: [
    "callback(...args);",
    "Reflect.get(target, 'value');",
    "const Reflect = { apply() {} }; Reflect.apply(fn, null, []);",
    "const local = { apply() {} }; const invoke = Reflect.apply; invoke = local.apply; invoke(fn, null, []);",
  ],
  invalid: [
    { code: "Reflect.apply(fn, null, []);", errors: [error] },
    { code: "globalThis.Reflect.apply(fn, null, []);", errors: [error] },
    {
      code: "const invoke = Reflect.apply; invoke(fn, null, []);",
      errors: [error],
    },
    {
      code: "const { apply: invoke } = Reflect; invoke(fn, null, []);",
      errors: [error],
    },
    { code: "Reflect.apply.call(Reflect, fn, null, []);", errors: [error] },
    { code: "Reflect.apply.apply(Reflect, [fn, null, []]);", errors: [error] },
    {
      code: "const invoke = Reflect.apply.bind(Reflect); invoke(fn, null, []);",
      errors: [error],
    },
  ],
});
