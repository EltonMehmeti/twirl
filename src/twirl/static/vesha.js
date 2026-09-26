// Vesha motion and feedback that needs a little script. Loaded with defer by both layouts.
(function () {
  // F2 · a plain form is on its way: busy button, and a second tap sends nothing.
  addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || form.matches("[hx-get], [hx-post]")) return;
    if (form.dataset.sent) { event.preventDefault(); return; }
    form.dataset.sent = "1";
    // form.elements skips buttons that belong to another form through form="…"
    var button = event.submitter || Array.prototype.find.call(form.elements, function (el) { return el.matches("button[type=submit], button:not([type])"); });
    if (button) { button.classList.add("is-busy"); button.setAttribute("aria-busy", "true"); }
  });
  // Back from the next page restores this one from the cache: make its forms usable again.
  addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll("form[data-sent]").forEach(function (form) {
      delete form.dataset.sent;
      form.querySelectorAll(".is-busy").forEach(function (b) { b.classList.remove("is-busy"); b.removeAttribute("aria-busy"); });
    });
  });

  // F3 · after a render with errors, open the keyboard where the fix is.
  var bad = document.querySelector(".v-field--error input:not([type=file]), .v-field--error select, .v-field--error textarea, form [aria-invalid=true]");
  if (bad) bad.focus({ preventScroll: false });

  // L1 · photos fade in once decoded.
  function ready(root) {
    root.querySelectorAll(".v-tile__img img, .v-gallery img").forEach(function (img) {
      function done() { img.classList.add("is-ready"); }
      if (img.complete) done();
      else { img.addEventListener("load", done, { once: true }); img.addEventListener("error", done, { once: true }); }
    });
  }
  ready(document);
  document.addEventListener("htmx:load", function (event) { ready(event.target); });

  // L2 · an upload fills its slot with real progress.
  document.addEventListener("htmx:xhr:progress", function (event) {
    var slot = event.target.closest && event.target.closest(".v-photo");
    if (!slot || !event.detail.lengthComputable) return;
    var p = event.detail.loaded / event.detail.total;
    slot.style.setProperty("--p", p.toFixed(3));
    var mark = slot.querySelector(".v-photo__mark");
    if (mark) mark.textContent = Math.round(p * 100) + "%";
  });

  // F5 · copy a link; the label itself says "Copied".
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".v-copy");
    if (!button || !navigator.clipboard) return;
    navigator.clipboard.writeText(new URL(button.dataset.url, location.href).href).then(function () {
      button.classList.add("is-done");
      var status = document.getElementById("v-copy-status");
      if (status) status.textContent = button.querySelector(".v-copy__b").textContent;
      clearTimeout(button.vTimer);
      button.vTimer = setTimeout(function () { button.classList.remove("is-done"); if (status) status.textContent = ""; }, 2000);
    });
  });
  // The clipboard needs a secure page; without it the button would do nothing, so it stays hidden.
  if (navigator.clipboard) document.querySelectorAll(".v-copy[hidden]").forEach(function (b) { b.hidden = false; });

  // N2 · the Request bar shows while the booking panel is below the screen.
  var bar = document.querySelector(".v-bookbar"), book = document.querySelector(".v-book");
  if (bar && book && "IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      var e = entries[0];
      bar.classList.toggle("is-on", !e.isIntersecting && e.boundingClientRect.top > 0);
    }).observe(book);
  }

  // G2 · contact sheet: tap outside or drag the handle down to close.
  document.querySelectorAll("[data-sheet]").forEach(function (opener) {
    var sheet = document.getElementById(opener.dataset.sheet);
    if (!sheet || !sheet.showModal) return;
    opener.addEventListener("click", function () { sheet.showModal(); });
    sheet.addEventListener("click", function (event) { if (event.target === sheet) sheet.close(); });
    var handle = sheet.querySelector(".v-sheet__handle"), y0 = 0, t0 = 0, dy = 0;
    if (!handle) return;
    handle.addEventListener("pointerdown", function (event) {
      y0 = event.clientY; t0 = event.timeStamp; dy = 0;
      handle.setPointerCapture(event.pointerId);
      sheet.classList.add("is-dragging");
    });
    handle.addEventListener("pointermove", function (event) {
      if (!sheet.classList.contains("is-dragging")) return;
      dy = Math.max(0, event.clientY - y0);
      sheet.style.setProperty("--drag", dy + "px");
    });
    function end(event) {
      if (!sheet.classList.contains("is-dragging")) return;
      sheet.classList.remove("is-dragging");
      if (dy > 80 || dy / Math.max(1, event.timeStamp - t0) > 0.5) sheet.close();
      sheet.style.removeProperty("--drag");
    }
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  });

  // R2·F2 · SMS code: slots fill as you type; the sixth digit sends the form.
  var code = document.querySelector(".v-input--code[data-autosubmit]");
  if (code) {
    var slots = code.closest(".v-field").querySelectorAll(".v-code__slots span");
    function paint() {
      var n = code.value.replace(/\D/g, "").length;
      slots.forEach(function (slot, i) { slot.classList.toggle("is-filled", i < n); });
      if (n === 6 && code.checkValidity() && !code.form.dataset.sent) code.form.requestSubmit();
    }
    code.addEventListener("input", paint);
    paint(); // iOS may have filled the field from the SMS before this ran
  }

  // R2·G1 · the calendar opens on today's column.
  var todayCell = document.querySelector(".calendar .is-today"), week = document.querySelector(".v-table-wrap");
  if (todayCell && week) week.scrollLeft = Math.max(0, todayCell.offsetLeft - 190 - 16);

  // R2·L1 · Today refreshes itself; rows that weren't there before rise in.
  var known = null;
  document.addEventListener("htmx:beforeSwap", function (event) {
    if (!event.detail.target || event.detail.target.id !== "board") return;
    // Logged out or an error page: keep the board that is on screen.
    if (!event.detail.xhr || event.detail.xhr.status !== 200 || event.detail.serverResponse.indexOf('id="board"') === -1) {
      event.detail.shouldSwap = false;
      return;
    }
    known = Array.prototype.map.call(document.querySelectorAll("#board [data-booking]"), function (li) { return li.dataset.booking; });
  });
  document.addEventListener("htmx:afterSettle", function () {
    if (!known) return;
    document.querySelectorAll("#board [data-booking]").forEach(function (li) {
      if (known.indexOf(li.dataset.booking) === -1) li.classList.add("is-new");
    });
    known = null;
  });
})();
