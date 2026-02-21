(function () {
  var THEME_KEY = 'ui-theme';

  function getTheme() {
    var current = document.documentElement.getAttribute('data-theme');
    if (current === 'light' || current === 'dark') {
      return current;
    }

    try {
      var saved = localStorage.getItem(THEME_KEY);
      if (saved === 'light' || saved === 'dark') {
        return saved;
      }
    } catch (e) {
      // Ignore storage read errors.
    }

    return 'dark';
  }

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (e) {
      // Ignore storage write errors.
    }
    updateToggleLabels(theme);
  }

  function updateToggleLabels(theme) {
    var nextThemeLabel = theme === 'light' ? 'Тёмная тема' : 'Светлая тема';
    document.querySelectorAll('[data-theme-toggle]').forEach(function (button) {
      button.textContent = nextThemeLabel;
    });
  }

  function toggleTheme() {
    var nextTheme = getTheme() === 'light' ? 'dark' : 'light';
    setTheme(nextTheme);
  }

  function bindToggleButtons(root) {
    (root || document).querySelectorAll('[data-theme-toggle]').forEach(function (button) {
      if (button.dataset.themeToggleBound === '1') {
        return;
      }
      button.dataset.themeToggleBound = '1';
      button.addEventListener('click', toggleTheme);
    });
  }

  function initThemeToggle() {
    var theme = getTheme();
    setTheme(theme);
    bindToggleButtons(document);

    document.body.addEventListener('htmx:afterSwap', function (event) {
      bindToggleButtons(event.target);
      updateToggleLabels(getTheme());
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initThemeToggle);
  } else {
    initThemeToggle();
  }
})();
