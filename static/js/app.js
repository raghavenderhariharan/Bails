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


/* Ground ledger sellers grid: live remaining + totals as the admin edits. */
(function () {
  "use strict";
  var form = document.getElementById("sellersForm");
  if (!form) return;
  var cur = (document.body.getAttribute("data-currency") || "\u20b9");
  var num = function (v) {
    var n = parseFloat(String(v == null ? "" : v).replace(/[^0-9.\-]/g, ""));
    return isFinite(n) ? n : 0;
  };
  // Indian digit grouping, whole rupees: 1234567 -> 12,34,567
  var inr = function (v) {
    var neg = v < 0, s = String(Math.abs(Math.round(v)));
    if (s.length > 3) {
      var tail = s.slice(-3), head = s.slice(0, -3), g = [];
      while (head.length > 2) { g.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) g.unshift(head);
      s = g.join(",") + "," + tail;
    }
    return (neg ? "-" : "") + cur + s;
  };
  var pct = function (v) {
    var s = (Math.round(v * 100) / 100).toFixed(2);
    return s + "%";
  };

  function recalc() {
    var closingT = 0, paidT = 0, shareT = 0;
    form.querySelectorAll("[data-ground-seller]").forEach(function (row) {
      var closingInput = row.querySelector("[data-ground-closing]");
      var closing = num(closingInput.value);
      var paid = num(closingInput.getAttribute("data-paid"));
      var share = num(row.querySelector("[data-ground-share]").value);
      var remaining = closing - paid;
      var cell = row.querySelector("[data-ground-remaining]");
      cell.textContent = inr(remaining);
      cell.classList.toggle("v-neg", remaining > 0);
      cell.classList.toggle("v-pos", remaining <= 0);
      closingT += closing; paidT += paid; shareT += share;
    });
    var set = function (sel, text) { var el = form.querySelector(sel); if (el) el.textContent = text; };
    set("[data-ground-share-total]", pct(shareT));
    set("[data-ground-closing-total]", inr(closingT));
    set("[data-ground-remaining-total]", inr(closingT - paidT));
  }
  form.addEventListener("input", function (e) {
    if (e.target.matches("[data-ground-closing],[data-ground-share],[data-ground-lease]")) recalc();
  });
})();

/* Ground purchase payment dialog (older sellers+payments ledger, admin-only). */
(function () {
  "use strict";
  var modal = document.getElementById("gpayModal");
  var form = document.getElementById("gpayForm");
  if (!modal || !form) return;
  var title = document.getElementById("gpayModalTitle");
  var createAction = form.getAttribute("action");
  var f = function (n) { return form.querySelector('[name="' + n + '"]'); };
  var open = function () { if (modal.showModal) modal.showModal(); else modal.setAttribute("open", ""); };
  var close = function () { if (modal.close) modal.close(); else modal.removeAttribute("open"); };

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-open-gpay]")) {
      form.setAttribute("action", createAction); form.reset();
      title.textContent = "Record payment";
      var d = f("txn_date"); if (d && !d.value) d.value = new Date().toISOString().slice(0, 10);
      open(); return;
    }
    var ed = event.target.closest("[data-edit-gpay]");
    if (ed) {
      var data = ed.dataset;
      form.setAttribute("action", "/ground/payment/" + data.id + "/edit");
      title.textContent = "Edit payment";
      f("detail").value = data.detail || "";
      f("ex_partner_id").value = data.ex || "";
      f("partner_id").value = data.partner || "";
      f("txn_number").value = data.number || "";
      f("txn_date").value = data.date || "";
      f("amount").value = data.amount || "";
      f("note").value = data.note || "";
      open(); return;
    }
    if (event.target.closest("[data-close-gpay]")) close();
  });
  modal.addEventListener("click", function (event) { if (event.target === modal) close(); });
})();

/* Ground calendar: open the block dialog for a day, disable taken slots. */
(function () {
  "use strict";
  var modal = document.getElementById("blockModal");
  var form = document.getElementById("blockForm");
  if (!modal || !form) return;
  var read = function (id) {
    var n = document.getElementById(id);
    try { return n ? JSON.parse(n.textContent) : []; } catch (e) { return []; }
  };
  var dates = read("calBookings"), slots = read("calSlots");
  var taken = {};
  dates.forEach(function (d, i) { (taken[d] = taken[d] || []).push(slots[i]); });

  var dateInput = document.getElementById("b-date");
  var full = form.querySelector("[data-full-day]");
  var picks = Array.prototype.slice.call(form.querySelectorAll("[data-slot]"));
  var note = document.getElementById("b-taken");

  function sync() {
    var t = taken[dateInput.value] || [];
    var fullTaken = t.indexOf(full.value) >= 0;
    picks.forEach(function (p) {
      p.disabled = fullTaken || t.indexOf(p.value) >= 0 || full.checked;
      if (p.disabled) p.checked = false;
    });
    full.disabled = fullTaken || t.length > 0;
    if (full.disabled) full.checked = false;
    note.textContent = fullTaken ? "This day is already blocked for the full day."
      : (t.length ? "Already blocked: " + t.join(", ") + "." : "");
  }

  function open(day) {
    form.reset();
    dateInput.value = day || new Date().toISOString().slice(0, 10);
    sync();
    if (modal.showModal) modal.showModal(); else modal.setAttribute("open", "");
  }
  function close() { if (modal.close) modal.close(); else modal.removeAttribute("open"); }

  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open-block]");
    if (opener) { open(opener.getAttribute("data-date")); return; }
    if (e.target.closest("[data-close-block]")) close();
  });
  document.addEventListener("keydown", function (e) {
    var cell = e.target.closest && e.target.closest(".cal__day[data-open-block]");
    if (cell && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(cell.getAttribute("data-date")); }
  });
  modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
  dateInput.addEventListener("change", sync);
  full.addEventListener("change", sync);
})();

/* Generic dialogs: [data-open-modal="id"] opens, [data-close-modal] closes. */
(function () {
  "use strict";
  function open(m) { if (m.showModal) m.showModal(); else m.setAttribute("open", ""); }
  function close(m) { if (m.close) m.close(); else m.removeAttribute("open"); }
  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open-modal]");
    if (opener) {
      var m = document.getElementById(opener.getAttribute("data-open-modal"));
      if (m) { m.dispatchEvent(new CustomEvent("bails:open")); open(m); }
      return;
    }
    var closer = e.target.closest("[data-close-modal]");
    if (closer) { var d = closer.closest("dialog"); if (d) close(d); return; }
    if (e.target.matches && e.target.matches("dialog.modal")) close(e.target);
  });
  // A submit button that needs its own confirmation (e.g. Remove inside a bigger form).
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-confirm-click]");
    if (b && !window.confirm(b.getAttribute("data-confirm-click"))) e.preventDefault();
  });
  window.BailsModal = { open: open, close: close };
})();

/* Period picker inside the Export / Send-mail dialogs: show only the inputs
   the chosen period needs, and disable the rest so they are not submitted. */
(function () {
  "use strict";
  function sync(picker) {
    var checked = picker.querySelector('input[name="period"]:checked');
    var kind = checked ? checked.value : "month";
    picker.querySelectorAll("[data-pp-show]").forEach(function (f) {
      var on = f.getAttribute("data-pp-show").split(" ").indexOf(kind) >= 0;
      f.hidden = !on;
      f.querySelectorAll("input,select").forEach(function (i) { i.disabled = !on; });
    });
    picker.dispatchEvent(new CustomEvent("bails:period", { bubbles: true }));
  }
  document.querySelectorAll("[data-period-picker]").forEach(function (p) {
    sync(p);
    p.addEventListener("change", function () { sync(p); });
  });
  window.BailsPeriodQuery = function (form) {
    var q = new URLSearchParams();
    form.querySelectorAll("[data-period-picker] input, [data-period-picker] select").forEach(function (i) {
      if (i.disabled || !i.name) return;
      if (i.type === "radio" && !i.checked) return;
      q.append(i.name, i.value);
    });
    return q;
  };
})();

/* Send mail: subject/body are written by the server for the chosen period. */
(function () {
  "use strict";
  var modal = document.getElementById("mailModal");
  var form = document.getElementById("mailForm");
  if (!modal || !form) return;
  var to = document.getElementById("m-to"), subject = document.getElementById("m-subject");
  var body = document.getElementById("m-body"), attach = document.getElementById("m-attach");
  var seq = 0;

  function refresh(fillRecipients) {
    var q = window.BailsPeriodQuery(form), mine = ++seq;
    attach.textContent = "Preparing…";
    fetch(form.getAttribute("data-draft-url") + "?" + q.toString(), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) {
        if (mine !== seq) return;
        subject.value = d.subject; body.value = d.body;
        attach.textContent = "Attachment: " + d.filename;
        if (fillRecipients || !to.value.trim()) to.value = (d.recipients || []).join("; ");
      })
      .catch(function () { attach.textContent = "Could not prepare the draft — check you are still signed in."; });
  }
  modal.addEventListener("bails:open", function () { refresh(true); });
  form.addEventListener("bails:period", function () { if (modal.open) refresh(false); });

  form.querySelector("[data-mail-gmail]").addEventListener("click", function () {
    var q = window.BailsPeriodQuery(form);
    // 1) download the workbook, 2) open a prefilled Gmail draft to attach it to.
    var a = document.createElement("a");
    a.href = form.getAttribute("data-export-url") + "?" + q.toString();
    a.download = ""; document.body.appendChild(a); a.click(); a.remove();
    var recipients = to.value.split(/[;,\s]+/).filter(Boolean).join(",");
    var url = "https://mail.google.com/mail/?view=cm&fs=1" +
      "&to=" + encodeURIComponent(recipients) +
      "&su=" + encodeURIComponent(subject.value) +
      "&body=" + encodeURIComponent(body.value);
    window.open(url, "_blank", "noopener");
  });
  form.addEventListener("submit", function () {
    var btn = form.querySelector('button[type="submit"]');
    if (btn) { btn.disabled = true; btn.lastChild.textContent = " Sending…"; }
  });
})();

/* Dashboard trend card: Graph or Table, one at a time (remembered). */
(function () {
  "use strict";
  document.querySelectorAll("[data-view-toggle]").forEach(function (card) {
    var key = "bails-view-" + card.getAttribute("data-view-toggle");
    function show(view) {
      card.querySelectorAll("[data-view-pane]").forEach(function (p) {
        p.hidden = p.getAttribute("data-view-pane") !== view;
      });
      card.querySelectorAll("[data-view]").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-view") === view ? "true" : "false");
      });
      try { localStorage.setItem(key, view); } catch (e) {}
    }
    var saved = null;
    try { saved = localStorage.getItem(key); } catch (e) {}
    show(saved === "table" ? "table" : "graph");
    card.addEventListener("click", function (e) {
      var b = e.target.closest("[data-view]");
      if (b) show(b.getAttribute("data-view"));
    });
  });
})();

/* Calendar: click a booking to move it, re-enter its details, or unblock it. */
(function () {
  "use strict";
  var modal = document.getElementById("bookingModal");
  var form = document.getElementById("bookingForm");
  if (!modal || !form) return;
  var base = form.getAttribute("data-action-base");
  var unblock = form.querySelector("[data-unblock]");
  document.addEventListener("click", function (e) {
    var chip = e.target.closest("[data-edit-booking]");
    if (!chip) return;
    e.stopPropagation(); // don't also open the day's "Block a date" dialog
    var d = chip.dataset;
    form.setAttribute("action", base + d.id + "/edit");
    unblock.setAttribute("formaction", base + d.id + "/delete");
    unblock.setAttribute("data-confirm-click", "Unblock " + d.slot + " on " + d.date + "?");
    form.querySelector('[name="booking_date"]').value = d.date;
    form.querySelector('[name="slot"]').value = d.slot;
    form.querySelector('[name="booked_by"]').value = d.by || "";
    form.querySelector('[name="note"]').value = d.note || "";
    window.BailsModal.open(modal);
  }, true);
})();

/* Partners grid: live share of the period's net and the equity total. */
(function () {
  "use strict";
  var form = document.getElementById("partnersForm");
  if (!form) return;
  var cur = (document.body.getAttribute("data-currency") || "₹");
  var net = parseFloat(form.getAttribute("data-net")) || 0;
  var inr = function (v) {
    var neg = v < 0, s = String(Math.abs(Math.round(v)));
    if (s.length > 3) {
      var tail = s.slice(-3), head = s.slice(0, -3), g = [];
      while (head.length > 2) { g.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) g.unshift(head);
      s = g.join(",") + "," + tail;
    }
    return (neg ? "-" : "") + cur + s;
  };
  function recalc() {
    var total = 0, shareTotal = 0;
    form.querySelectorAll("[data-partner-row]").forEach(function (row) {
      var eq = parseFloat(row.querySelector("[data-equity]").value) || 0;
      var on = row.querySelector("[data-active]").checked;
      var share = on ? net * eq / 100 : 0;
      var cell = row.querySelector("[data-share]");
      cell.textContent = on ? inr(share) : "—";
      cell.classList.toggle("v-neg", share < 0);
      row.classList.toggle("row--muted", !on);
      if (on) { total += eq; shareTotal += share; }
    });
    var t = Math.round(total * 100) / 100;
    form.querySelector("[data-equity-total]").textContent = t.toFixed(2) + "%";
    form.querySelector("[data-share-total]").textContent = inr(shareTotal);
    var note = form.querySelector("[data-equity-note]");
    note.textContent = t === 100 ? "Balanced" : "Should total 100% (" + (t > 100 ? "+" : "") + (t - 100).toFixed(2) + "%)";
    note.className = "small " + (t === 100 ? "v-pos" : "v-neg");
  }
  form.addEventListener("input", recalc);
  form.addEventListener("change", recalc);
  recalc();
})();
