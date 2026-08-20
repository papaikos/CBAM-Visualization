/** Keyboard commit behaviors and the CO₂ price display echo in the toolbar. */

export function commitFieldOnEnter(event) {
  if (event.key !== "Enter") return false;
  event.preventDefault();
  event.currentTarget.blur();
  return true;
}

export function commitCountrySearchOnEnter(event, matchedCountry, resultsElement) {
  const normalizedCountry = String(matchedCountry ?? "").trim();
  if (event.key !== "Enter" || !normalizedCountry) return false;

  event.preventDefault();
  event.currentTarget.value = normalizedCountry;
  event.currentTarget.dispatchEvent(new Event("input", { bubbles: true }));
  resultsElement?.classList.add("hidden");
  event.currentTarget.blur();
  return true;
}

export function formatCommittedPrice(value) {
  const normalized = String(value ?? "").trim();
  return normalized ? `${normalized} €` : "";
}

export function initToolbarInteractions() {
  const cnCodeInput = document.querySelector("#cn-code-input");
  const priceInput = document.querySelector("#co2-price-input");
  const priceShell = document.querySelector(".co2-input-shell");
  const priceDisplay = document.querySelector("#co2-price-display");
  const countrySearchInput = document.querySelector("#country-search-input");
  const countrySearchResults = document.querySelector("#country-search-results");

  for (const input of [cnCodeInput, priceInput]) {
    input?.addEventListener("keydown", commitFieldOnEnter);
  }

  countrySearchInput?.addEventListener(
    "keydown",
    (event) => {
      const matchedCountry =
        countrySearchResults?.querySelector(".search-result")?.dataset.country;
      commitCountrySearchOnEnter(event, matchedCountry, countrySearchResults);
    },
    { capture: true },
  );

  if (priceInput && priceShell && priceDisplay) {
    const syncPriceDisplay = () => {
      const formatted = formatCommittedPrice(priceInput.value);
      priceDisplay.textContent = formatted;
      priceShell.classList.toggle("has-price-value", Boolean(formatted));
    };

    priceInput.addEventListener("input", syncPriceDisplay);
    priceInput.addEventListener("change", syncPriceDisplay);
    syncPriceDisplay();
  }
}
