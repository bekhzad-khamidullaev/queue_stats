(function () {
  function toInt(value, fallback) {
    var parsed = parseInt(String(value || ""), 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function isHeavySelect(selectEl) {
    var threshold = toInt(selectEl.getAttribute("data-select2-heavy-threshold"), 250);
    return (selectEl.options && selectEl.options.length > threshold) || false;
  }

  function buildOptions(selectEl) {
    var options = {
      width: "100%",
      closeOnSelect: false,
      dropdownAutoWidth: true
    };

    var placeholder = selectEl.getAttribute("data-placeholder");
    if (placeholder) {
      options.placeholder = placeholder;
    }

    if (isHeavySelect(selectEl)) {
      options.minimumInputLength = 1;
    }

    return options;
  }

  function initSingleSelect(selectEl) {
    var $select = window.jQuery(selectEl);
    if ($select.data("select2")) {
      return;
    }
    $select.select2(buildOptions(selectEl));
  }

  function bindLazyInit(selectEl) {
    if (selectEl.dataset.select2LazyBound === "1") {
      return;
    }
    selectEl.dataset.select2LazyBound = "1";

    var lazyInit = function () {
      initSingleSelect(selectEl);
      selectEl.removeEventListener("focusin", lazyInit);
      selectEl.removeEventListener("pointerdown", lazyInit);
      selectEl.removeEventListener("keydown", lazyInit);
    };

    selectEl.addEventListener("focusin", lazyInit, { once: true });
    selectEl.addEventListener("pointerdown", lazyInit, { once: true });
    selectEl.addEventListener("keydown", lazyInit, { once: true });
  }

  function initSelect2(root) {
    if (typeof window.jQuery === 'undefined' || typeof window.jQuery.fn.select2 === 'undefined') {
      return;
    }

    var $root = root ? window.jQuery(root) : window.jQuery(document);
    $root.find('select.radix-select-multi').each(function () {
      if (isHeavySelect(this)) {
        bindLazyInit(this);
      } else {
        initSingleSelect(this);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initSelect2(document);
    });
  } else {
    initSelect2(document);
  }

  document.body.addEventListener('htmx:afterSwap', function (event) {
    initSelect2(event.target);
  });
})();
