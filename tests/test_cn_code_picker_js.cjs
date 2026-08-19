const assert = require("node:assert/strict");
const test = require("node:test");

const {
  commitSelectedCode,
  moveActiveIndex,
  openFullCodeMenu,
} = require("../public/cn-code-picker.js");

test("selecting a code commits the change and releases input focus", () => {
  const dispatchedEvents = [];
  const input = {
    value: "",
    blurCalls: 0,
    dispatchEvent(event) {
      dispatchedEvents.push(event);
      return true;
    },
    blur() {
      this.blurCalls += 1;
    },
  };

  commitSelectedCode(input, "76012030");

  assert.equal(input.value, "76012030");
  assert.equal(dispatchedEvents.length, 1);
  assert.equal(dispatchedEvents[0].type, "change");
  assert.equal(dispatchedEvents[0].bubbles, true);
  assert.equal(input.blurCalls, 1);
});

test("arrow menu keeps every code when the input already has a selected value", () => {
  const opened = openFullCodeMenu(
    ["25231000", "76011010", "76012030"],
    "76011010",
  );
  assert.deepEqual(opened.codes, ["25231000", "76011010", "76012030"]);
  assert.equal(opened.activeIndex, 1);
});

test("arrow menu keyboard navigation wraps through the complete list", () => {
  assert.equal(moveActiveIndex(2, 1, 3), 0);
  assert.equal(moveActiveIndex(0, -1, 3), 2);
  assert.equal(moveActiveIndex(-1, 1, 3), 0);
  assert.equal(moveActiveIndex(0, 1, 0), -1);
});
