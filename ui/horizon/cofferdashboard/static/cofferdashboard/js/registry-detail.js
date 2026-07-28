(function () {
  "use strict";

  function legacyCopy(value) {
    var field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    var copied = document.execCommand("copy");
    document.body.removeChild(field);
    return copied ? Promise.resolve() : Promise.reject(new Error("copy failed"));
  }

  function copy(value) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(value);
    }
    return legacyCopy(value);
  }

  function translate(message) {
    return typeof gettext === "function" ? gettext(message) : message;
  }

  function status(message, isError) {
    document.querySelectorAll(".coffer-copy-status").forEach(function (element) {
      element.textContent = message;
      element.classList.toggle("text-danger", isError);
      element.classList.toggle("text-success", !isError);
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest(".coffer-copy-button");
    if (!button) {
      return;
    }
    var target = document.getElementById(button.getAttribute("data-copy-target"));
    if (!target) {
      status(translate("Unable to copy this value."), true);
      return;
    }
    copy(target.textContent.trim()).then(
      function () {
        status(translate("Copied to clipboard."), false);
      },
      function () {
        status(
          translate("Copy failed. Select and copy the value manually."),
          true
        );
      }
    );
  });
})();
