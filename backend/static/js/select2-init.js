(function () {
  function initSelect2(root) {
    if (typeof window.jQuery === 'undefined' || typeof window.jQuery.fn.select2 === 'undefined') {
      return;
    }

    var $root = root ? window.jQuery(root) : window.jQuery(document);
    $root.find('select.radix-select-multi').each(function () {
      var $select = window.jQuery(this);
      if ($select.data('select2')) {
        return;
      }

      $select.select2({
        width: '100%',
        closeOnSelect: false,
        dropdownAutoWidth: true
      });
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
