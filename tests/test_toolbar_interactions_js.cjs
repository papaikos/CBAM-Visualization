const assert = require("node:assert/strict");
const test = require("node:test");

const {
  commitCountrySearchOnEnter,
  commitFieldOnEnter,
  formatCommittedPrice,
} = require("../public/toolbar-interactions.js");

test("Enter accepts the suggested country name and releases the search field", () => {
  const dispatchedEvents = [];
  const input = {
    value: "china",
    blurCalls: 0,
    blur() {
      this.blurCalls += 1;
    },
    dispatchEvent(event) {
      dispatchedEvents.push(event);
    },
  };
  const hiddenClasses = [];
  const results = {
    classList: {
      add(className) {
        hiddenClasses.push(className);
      },
    },
  };
  const event = {
    key: "Enter",
    currentTarget: input,
    preventDefaultCalls: 0,
    preventDefault() {
      this.preventDefaultCalls += 1;
    },
  };

  assert.equal(commitCountrySearchOnEnter(event, "China", results), true);
  assert.equal(input.value, "China");
  assert.equal(input.blurCalls, 1);
  assert.equal(event.preventDefaultCalls, 1);
  assert.deepEqual(hiddenClasses, ["hidden"]);
  assert.equal(dispatchedEvents.length, 1);
  assert.equal(dispatchedEvents[0].type, "input");
  assert.equal(dispatchedEvents[0].bubbles, true);
});

test("Enter commits a toolbar field and releases focus", () => {
  const input = {
    blurCalls: 0,
    blur() {
      this.blurCalls += 1;
    },
  };
  const event = {
    key: "Enter",
    currentTarget: input,
    preventDefaultCalls: 0,
    preventDefault() {
      this.preventDefaultCalls += 1;
    },
  };

  assert.equal(commitFieldOnEnter(event), true);
  assert.equal(event.preventDefaultCalls, 1);
  assert.equal(input.blurCalls, 1);
});

test("non-Enter keys keep the toolbar field in editing mode", () => {
  const input = {
    blurCalls: 0,
    blur() {
      this.blurCalls += 1;
    },
  };
  const event = {
    key: "ArrowDown",
    currentTarget: input,
    preventDefaultCalls: 0,
    preventDefault() {
      this.preventDefaultCalls += 1;
    },
  };

  assert.equal(commitFieldOnEnter(event), false);
  assert.equal(event.preventDefaultCalls, 0);
  assert.equal(input.blurCalls, 0);
});

test("a committed numeric price displays with a euro suffix", () => {
  assert.equal(formatCommittedPrice("100"), "100 €");
  assert.equal(formatCommittedPrice("65.50"), "65.50 €");
  assert.equal(formatCommittedPrice(""), "");
  assert.equal(formatCommittedPrice("   "), "");
});
