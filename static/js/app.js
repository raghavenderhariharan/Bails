/* Bails Ledger — UI behaviour: entry dialog, theme, delete confirmation. */
(function () {
  "use strict";

  // ----------------------------- theme ----------------------------------
  var THEME_KEY = "bails-theme";

  function currentTheme() {
    var set = document.documentElement.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  var toggle = document.getElementById("themeToggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      document.dispatchEvent(new CustomEvent("bails:themechange", { detail: { theme: next } }));
    });
  }

  // --------------------------- entry dialog ------------------------------
  var modal = document.getElementById("entryModal");
  if (!modal) return;

  var form = document.getElementById("entryForm");
  var title = document.getElementById("entryModalTitle");
  var submit = document.getElementById("entrySubmit");
  var categorySelect = document.getElementById("e-category");
  var groupIncome = document.getElementById("optIncome");
  var groupExpense = document.getElementById("optExpense");
  var createAction = form.getAttribute("action");

  function field(name) { return form.querySelector('[name="' + name + '"]'); }

  /* Show only the categories that belong to the chosen kind, so an expense can
     never be filed under an income category. */
  function syncCategories(kind, keepValue) {
    var isIncome = kind === "income";
    groupIncome.hidden = !isIncome;
    groupExpense.hidden = isIncome;
    Array.prototype.forEach.call(groupIncome.children, function (o) { o.disabled = !isIncome; });
    Array.prototype.forEach.call(groupExpense.children, function (o) { o.disabled = isIncome; });

    var allowed = Array.prototype.map.call(
      (isIncome ? groupIncome : groupExpense).children, function (o) { return o.value; });
    if (keepValue && allowed.indexOf(keepValue) !== -1) {
      categorySelect.value = keepValue;
    } else if (allowed.indexOf(categorySelect.value) === -1) {
      categorySelect.value = "";
    }
  }

  var watchmanField = document.getElementById("watchmanField");

  function setKind(kind, keepCategory) {
    var radio = form.querySelector('input[name="kind"][value="' + kind + '"]');
    if (radio) radio.checked = true;
    syncCategories(kind, keepCategory);
    submit.classList.toggle("btn--credit", kind === "income");
    submit.classList.toggle("btn--debit", kind === "expense");
    submit.classList.toggle("btn--primary", false);
    // The watchman (petty-cash) tag only applies to expenses.
    if (watchmanField) {
      var isExpense = kind === "expense";
      watchmanField.hidden = !isExpense;
      if (!isExpense) {
        var w = field("watchman_id");
        if (w) w.value = "";
      }
    }
    // On a new entry, keep the heading in step with the chosen type.
    if (form.getAttribute("action") === createAction) {
      title.textContent = kind === "expense" ? "New expense (debit)" : "New income (credit)";
    }
  }

  Array.prototype.forEach.call(form.querySelectorAll('input[name="kind"]'), function (radio) {
    radio.addEventListener("change", function () { setKind(radio.value, null); });
  });

  function open() {
    if (typeof modal.showModal === "function") modal.showModal();
    else modal.setAttribute("open", "");
  }

  function close() {
    if (typeof modal.close === "function") modal.close();
    else modal.removeAttribute("open");
  }

  function resetForCreate(kind) {
    form.setAttribute("action", createAction);
    form.reset();
    title.textContent = kind === "expense" ? "New expense (debit)" : "New income (credit)";
    submit.textContent = "Save entry";
    setKind(kind || "income", null);
    var dateField = field("txn_date");
    if (dateField && !dateField.value) dateField.value = new Date().toISOString().slice(0, 10);
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-open-entry]");
    if (opener) {
      resetForCreate(opener.getAttribute("data-kind") || "income");
      open();
      var amount = field("amount");
      if (amount) setTimeout(function () { amount.focus(); }, 60);
      return;
    }

    var editor = event.target.closest("[data-edit-entry]");
    if (editor) {
      var data = editor.dataset;
      form.setAttribute("action", "/transactions/" + data.id + "/edit");
      title.textContent = "Edit entry";
      submit.textContent = "Save changes";
      field("txn_date").value = data.date || "";
      field("amount").value = data.amount || "";
      field("description").value = data.description || "";
      field("slot").value = data.slot || "";
      field("party").value = data.party || "";
      field("notes").value = data.notes || "";
      setKind(data.kind || "income", data.category || "");
      var wsel = field("watchman_id");
      if (wsel) wsel.value = (data.kind === "expense" && data.watchman) ? data.watchman : "";
      open();
      return;
    }

    if (event.target.closest("[data-close-entry]")) close();
  });

  // Click on the backdrop (outside the form) closes the dialog.
  modal.addEventListener("click", function (event) {
    if (event.target === modal) close();
  });

  // ------------------------ destructive actions --------------------------
  document.addEventListener("submit", function (event) {
    var form = event.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.getAttribute("data-confirm"))) {
      event.preventDefault();
    }
  });
})();

/* Admin restore-from-backup dialog. Enables the destructive button only once
   the admin types RESTORE; the server re-checks it regardless. */
(function () {
  "use strict";
  var modal = document.getElementById("restoreModal");
  if (!modal) return;

  var confirmInput = document.getElementById("r-confirm");
  var submit = document.getElementById("restoreSubmit");

  function open() { if (modal.showModal) modal.showModal(); else modal.setAttribute("open", ""); }
  function close() { if (modal.close) modal.close(); else modal.removeAttribute("open"); }

  function syncButton() {
    submit.disabled = (confirmInput.value || "").trim().toUpperCase() !== "RESTORE";
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-open-restore]")) {
      var form = document.getElementById("restoreForm");
      if (form) form.reset();
      syncButton();
      open();
      return;
    }
    if (event.target.closest("[data-close-restore]")) close();
  });

  if (confirmInput) confirmInput.addEventListener("input", syncButton);
  modal.addEventListener("click", function (event) { if (event.target === modal) close(); });
})();


/* Ground investment summary: live pending + totals as the admin edits (lakh). */
(function () {
  "use strict";
  var form = document.getElementById("groundForm");
  if (!form) return;
  var cur = (document.body.getAttribute("data-currency") || "\u20b9");
  var num = function (v) {
    var n = parseFloat(String(v == null ? "" : v).replace(/[^0-9.\-]/g, ""));
    return isFinite(n) ? n : 0;
  };
  var trim = function (v) {
    var s = (Math.round(v * 100) / 100).toFixed(2);
    if (s.indexOf(".") >= 0) s = s.replace(/0+$/, "").replace(/\.$/, "");
    return s || "0";
  };
  var money = function (v) { return cur + trim(v); };

  function recalc() {
    var shareT = 0, invT = 0, recT = 0, pendT = 0, adjT = 0;
    form.querySelectorAll("[data-ground-row]").forEach(function (row) {
      var inv = num(row.querySelector("[data-ground-invest]").value);
      var rec = num(row.querySelector("[data-ground-received]").value);
      var share = num(row.querySelector("[data-ground-share]").value);
      var adj = num(row.querySelector("[data-ground-adjust]").value);
      var pend = inv - rec;
      var cell = row.querySelector("[data-ground-pending]");
      cell.textContent = money(pend);
      cell.classList.toggle("v-neg", pend > 0);
      cell.classList.toggle("v-pos", pend <= 0);
      shareT += share; invT += inv; recT += rec; pendT += pend; adjT += adj;
    });
    var set = function (sel, text) { var el = form.querySelector(sel); if (el) el.textContent = text; };
    set("[data-ground-share-total]", trim(shareT) + "%");
    set("[data-ground-invest-total]", money(invT));
    set("[data-ground-received-total]", money(recT));
    set("[data-ground-pending-total]", money(pendT));
    set("[data-ground-adjust-total]", money(adjT));
  }
  form.addEventListener("input", function (e) {
    if (e.target.matches("[data-ground-invest],[data-ground-received],[data-ground-share],[data-ground-adjust],[data-ground-stated]")) recalc();
  });
})();
