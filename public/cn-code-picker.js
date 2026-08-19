"use strict";

function openFullCodeMenu(codes, currentValue) {
  const uniqueCodes = [...new Set(codes.map((code) => String(code).trim()).filter(Boolean))];
  const selectedIndex = uniqueCodes.indexOf(String(currentValue ?? "").trim());
  return {
    codes: uniqueCodes,
    activeIndex: selectedIndex >= 0 ? selectedIndex : uniqueCodes.length ? 0 : -1,
  };
}

function moveActiveIndex(currentIndex, direction, length) {
  if (length <= 0) return -1;
  const start = currentIndex < 0 ? (direction < 0 ? 0 : -1) : currentIndex;
  return (start + direction + length) % length;
}

function commitSelectedCode(input, code) {
  input.value = code;
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.blur();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { commitSelectedCode, moveActiveIndex, openFullCodeMenu };
}

if (typeof document !== "undefined") {
  const input = document.querySelector("#cn-code-input");
  const datalist = document.querySelector("#cn-code-options");
  const toggle = document.querySelector("#cn-code-menu-toggle");
  const menu = document.querySelector("#cn-code-menu");
  const shell = document.querySelector(".cn-code-input-shell");

  if (input && datalist && toggle && menu && shell) {
    let menuState = { codes: [], activeIndex: -1 };

    const availableCodes = () =>
      Array.from(datalist.options, (option) => option.value).filter(Boolean);

    const syncAvailability = () => {
      toggle.disabled = availableCodes().length === 0;
    };

    const closeMenu = ({ returnFocus = false } = {}) => {
      menu.classList.add("hidden");
      menu.replaceChildren();
      toggle.setAttribute("aria-expanded", "false");
      if (returnFocus) toggle.focus();
    };

    const focusOption = (index) => {
      const options = menu.querySelectorAll(".cn-code-menu-option");
      options[index]?.focus();
      options[index]?.scrollIntoView({ block: "nearest" });
    };

    const selectCode = (code) => {
      closeMenu();
      commitSelectedCode(input, code);
    };

    const renderMenu = () => {
      const fragment = document.createDocumentFragment();
      menuState.codes.forEach((code, index) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "cn-code-menu-option";
        option.dataset.code = code;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", String(index === menuState.activeIndex));
        option.textContent = code;
        fragment.append(option);
      });
      menu.replaceChildren(fragment);
      menu.classList.remove("hidden");
      toggle.setAttribute("aria-expanded", "true");
      focusOption(menuState.activeIndex);
    };

    const openMenu = () => {
      menuState = openFullCodeMenu(availableCodes(), input.value);
      if (!menuState.codes.length) return;
      renderMenu();
    };

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      if (menu.classList.contains("hidden")) openMenu();
      else closeMenu({ returnFocus: true });
    });

    menu.addEventListener("click", (event) => {
      const option = event.target.closest(".cn-code-menu-option");
      if (option) selectCode(option.dataset.code);
    });

    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu({ returnFocus: true });
        return;
      }
      if (event.key === "Tab") {
        closeMenu();
        return;
      }
      const directions = { ArrowDown: 1, ArrowUp: -1 };
      if (directions[event.key]) {
        event.preventDefault();
        menuState.activeIndex = moveActiveIndex(
          menuState.activeIndex,
          directions[event.key],
          menuState.codes.length,
        );
        focusOption(menuState.activeIndex);
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        menuState.activeIndex = event.key === "Home" ? 0 : menuState.codes.length - 1;
        focusOption(menuState.activeIndex);
      }
    });

    input.addEventListener("input", () => closeMenu());
    document.addEventListener("pointerdown", (event) => {
      if (!shell.contains(event.target)) closeMenu();
    });

    new MutationObserver(syncAvailability).observe(datalist, { childList: true });
    syncAvailability();
  }
}
