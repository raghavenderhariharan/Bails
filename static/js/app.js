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

  // Say what a period backup will do before it is restored.
  var file = document.getElementById("r-file"), note = document.getElementById("r-period-note");
  if (file && note && window.FileReader) {
    file.addEventListener("change", function () {
      note.hidden = true;
      var f = file.files && file.files[0];
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () {
        var data;
        try { data = JSON.parse(reader.result); } catch (e) { return; }
        if (!data || typeof data !== "object") return;
        if (data.scope && data.scope.label) {
          note.textContent = "This backup only holds " + data.scope.label + ". Restoring it replaces " +
            data.scope.label + "’s entries and calendar bookings; everything else stays as it is.";
          note.hidden = false;
        } else if (data.period) {
          note.textContent = "This backup only holds " + data.period + ". Every entry, partner, watchman, " +
            "booking and payment is replaced by it, so entries outside " + data.period +
            " will be gone. Download a full backup first if you might need them.";
          note.hidden = false;
        }
      };
      reader.readAsText(f);
    });
  }
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

  function open(day, slot) {
    form.reset();
    dateInput.value = day || new Date().toISOString().slice(0, 10);
    if (slot) {
      var pick = form.querySelector('input[name="slot"][value="' + slot + '"]');
      if (pick) pick.checked = true;
    }
    sync();
    if (modal.showModal) modal.showModal(); else modal.setAttribute("open", "");
  }
  function close() { if (modal.close) modal.close(); else modal.removeAttribute("open"); }

  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open-block]");
    if (opener) { open(opener.getAttribute("data-date"), opener.getAttribute("data-slot")); return; }
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
      var from = opener.closest("dialog");
      if (m) {
        if (from && from !== m) {
          close(from);
          if (window.BailsCopyPeriod) window.BailsCopyPeriod(from, m);
        }
        m.dispatchEvent(new CustomEvent("bails:open")); open(m);
      }
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

/* Period picker inside the Export / Send-mail dialogs: Monthly / Quarterly /
   Yearly / All, previous/next arrows, and a preview fetched from the server. */
(function () {
  "use strict";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function q(picker, sel) { return picker.querySelector(sel); }
  function state(picker) {
    var m = (q(picker, "[data-pp-month]").value || "").split("-");
    return {
      kind: q(picker, "[data-pp-kind]").value || "month",
      mYear: parseInt(m[0], 10) || new Date().getFullYear(),
      month: parseInt(m[1], 10) || (new Date().getMonth() + 1),
      year: parseInt(q(picker, "[data-pp-year]").value, 10) || new Date().getFullYear(),
      quarter: parseInt(q(picker, "[data-pp-quarter]").value, 10) || 1
    };
  }
  function save(picker, st) {
    q(picker, "[data-pp-kind]").value = st.kind;
    q(picker, "[data-pp-month]").value = st.mYear + "-" + (st.month < 10 ? "0" : "") + st.month;
    q(picker, "[data-pp-year]").value = st.year;
    q(picker, "[data-pp-quarter]").value = st.quarter;
  }
  function label(st) {
    if (st.kind === "month") return MONTHS[st.month - 1] + " " + st.mYear;
    if (st.kind === "quarter") {
      var f = 3 * (st.quarter - 1);
      return "Q" + st.quarter + " " + st.year + " (" + MONTHS[f] + "–" + MONTHS[f + 2] + ")";
    }
    if (st.kind === "year") return "Year " + st.year;
    return "All time";
  }
  function query(picker) {
    var st = state(picker), p = new URLSearchParams();
    p.append("period", st.kind);
    if (st.kind === "month") p.append("month", q(picker, "[data-pp-month]").value);
    if (st.kind === "quarter" || st.kind === "year") p.append("year", st.year);
    if (st.kind === "quarter") p.append("quarter", st.quarter);
    return p;
  }
  function render(picker) {
    var st = state(picker), form = picker.closest("form");
    // Only the inputs this kind needs are submitted.
    q(picker, "[data-pp-month]").disabled = st.kind !== "month";
    q(picker, "[data-pp-year]").disabled = !(st.kind === "quarter" || st.kind === "year");
    q(picker, "[data-pp-quarter]").disabled = st.kind !== "quarter";
    picker.querySelectorAll("[data-pp-step]").forEach(function (b) { b.disabled = st.kind === "all"; });
    picker.querySelectorAll('input[type="radio"]').forEach(function (r) { r.checked = r.value === st.kind; });
    q(picker, "[data-pp-label]").textContent = label(st);
    if (form) {
      form.querySelectorAll("[data-pp-hide-all]").forEach(function (el) { el.hidden = st.kind === "all"; });
      var bk = form.querySelector("[data-pv-backup]");
      if (bk) bk.textContent = st.kind === "all" ? "Download full backup" : "Download backup · " + label(st);
    }
    preview(picker);
    picker.dispatchEvent(new CustomEvent("bails:period", { bubbles: true }));
  }
  var seq = 0;
  function preview(picker) {
    var url = picker.getAttribute("data-preview-url"), mine = ++seq, form = picker.closest("form");
    if (!url) return;
    fetch(url + "?" + query(picker).toString(), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) {
        if (mine !== seq) return;
        q(picker, "[data-pp-label]").textContent = d.label;
        ["opening", "income", "expense", "closing"].forEach(function (k) {
          var el = picker.querySelector('[data-pv="' + k + '"]'); if (el) el.textContent = d[k];
        });
        var c = picker.querySelector('[data-pv="count"]');
        if (c) c.textContent = d.count + (d.count === 1 ? " entry" : " entries") + " in " + d.label;
        if (form) {
          var cal = form.querySelector('[data-pv="calendar"]');
          if (cal) cal.textContent = d.days_blocked ? d.days_blocked + " day(s) with bookings, " +
            d.full_days + " full day(s), " + d.blocked_slots + " slot(s) blocked." : "Nothing blocked in " + d.label + ".";
          form.querySelectorAll("[data-pv-file]").forEach(function (el) {
            el.textContent = (d.files || {})[el.getAttribute("data-pv-file")] || "";
          });
        }
      })
      .catch(function () {});
  }
  function step(picker, dir) {
    var st = state(picker);
    if (st.kind === "month") {
      st.month += dir;
      if (st.month < 1) { st.month = 12; st.mYear -= 1; }
      if (st.month > 12) { st.month = 1; st.mYear += 1; }
    } else if (st.kind === "quarter") {
      st.quarter += dir;
      if (st.quarter < 1) { st.quarter = 4; st.year -= 1; }
      if (st.quarter > 4) { st.quarter = 1; st.year += 1; }
    } else if (st.kind === "year") {
      st.year += dir;
    }
    save(picker, st); render(picker);
  }
  function setKind(picker, kind) {
    var st = state(picker);
    // Keep the same point in time when switching between kinds.
    if (st.kind === "month" && kind !== "month") { st.year = st.mYear; st.quarter = Math.floor((st.month - 1) / 3) + 1; }
    if (st.kind !== "month" && kind === "month" && st.kind !== "all") {
      st.mYear = st.year; st.month = st.kind === "quarter" ? 3 * st.quarter : (st.year === new Date().getFullYear() ? new Date().getMonth() + 1 : 12);
    }
    st.kind = kind; save(picker, st); render(picker);
  }
  document.querySelectorAll("[data-period-picker]").forEach(function (p) {
    p.addEventListener("change", function (e) {
      if (e.target.type === "radio") setKind(p, e.target.value);
    });
    p.addEventListener("click", function (e) {
      var b = e.target.closest("[data-pp-step]");
      if (b) step(p, parseInt(b.getAttribute("data-pp-step"), 10));
    });
    var dialog = p.closest("dialog");
    if (dialog) dialog.addEventListener("bails:open", function () { render(p); });
    render(p);
  });
  window.BailsPeriodQuery = function (form) {
    var p = form.querySelector("[data-period-picker]");
    return p ? query(p) : new URLSearchParams();
  };
  // Carry the chosen period from one dialog's picker into another's.
  window.BailsCopyPeriod = function (from, to) {
    var a = from && from.querySelector("[data-period-picker]"), b = to && to.querySelector("[data-period-picker]");
    if (!a || !b) return;
    ["kind", "month", "year", "quarter"].forEach(function (k) {
      b.querySelector("[data-pp-" + k + "]").value = a.querySelector("[data-pp-" + k + "]").value;
    });
    render(b);
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
  var seq = 0, defaults = [];
  form.querySelector("[data-mail-defaults]").addEventListener("click", function () {
    if (defaults.length) to.value = defaults.join("; ");
  });

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
        defaults = d.defaults || defaults;
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
      var sw = card.querySelector("[data-view-switch]");
      if (sw) sw.textContent = sw.getAttribute("data-label-" + view);
      current = view;
      try { localStorage.setItem(key, view); } catch (e) {}
    }
    var current = "graph", saved = null;
    try { saved = localStorage.getItem(key); } catch (e) {}
    show(saved === "table" ? "table" : "graph");
    card.addEventListener("click", function (e) {
      if (e.target.closest("[data-view-switch]")) show(current === "graph" ? "table" : "graph");
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
    e.stopPropagation(); // don't also open the day sheet underneath
    var host = chip.closest("dialog");
    if (host && host !== modal) window.BailsModal.close(host);
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
  var lease = parseFloat(form.getAttribute("data-lease")) || 0;
  function recalc() {
    var total = 0, shareTotal = 0, leaseTotal = 0;
    form.querySelectorAll("[data-partner-row]").forEach(function (row) {
      var eq = parseFloat(row.querySelector("[data-equity]").value) || 0;
      var on = row.querySelector("[data-active]").checked;
      var share = on ? net * eq / 100 : 0;
      var cell = row.querySelector("[data-share]");
      cell.textContent = on ? inr(share) : "Inactive";
      cell.classList.toggle("v-neg", share < 0);
      cell.classList.toggle("muted", !on);
      var split = lease * eq / 100, paid = parseFloat(row.getAttribute("data-paid")) || 0;
      row.querySelector("[data-lease-split]").textContent = inr(split);
      var left = row.querySelector("[data-lease-left]");
      if (left) left.textContent = inr(split - paid) + " left";
      row.classList.toggle("row--muted", !on);
      if (on) { total += eq; shareTotal += share; }
      leaseTotal += split;
    });
    var t = Math.round(total * 100) / 100;
    form.querySelector("[data-equity-total]").textContent = t.toFixed(2) + "%";
    form.querySelector("[data-equity-total]").classList.toggle("v-warn", t !== 100);
    form.querySelector("[data-share-total]").textContent = inr(shareTotal);
    form.querySelector("[data-lease-total]").textContent = inr(leaseTotal);
    var note = form.querySelector("[data-equity-note]");
    note.textContent = t === 100 ? "Balanced" : "Should total 100% (" + (t > 100 ? "+" : "") + (t - 100).toFixed(2) + "%)";
    note.className = "small " + (t === 100 ? "v-pos" : "v-warn");
  }
  form.addEventListener("input", recalc);
  form.addEventListener("change", recalc);
  recalc();
})();

/* Calendar day sheet: the day's blocks with Unblock / Edit, "Unblock the whole
   day", and a "Just unblocked" list with Re-block (the re-entry). */
(function () {
  "use strict";
  var modal = document.getElementById("dayModal");
  if (!modal) return;
  var read = function (id) {
    var n = document.getElementById(id);
    try { return n ? JSON.parse(n.textContent) : []; } catch (e) { return []; }
  };
  var all = read("calDay"), unblocked = read("calFreed");
  var admin = modal.getAttribute("data-admin") === "1";
  var csrf = modal.getAttribute("data-csrf"), month = modal.getAttribute("data-month");
  var body = modal.querySelector("[data-day-body]"), title = document.getElementById("dayModalTitle");
  var blockBtn = modal.querySelector("[data-day-block]");
  var SLOTS = ["Full Day", "7:00 AM", "10:45 AM", "2:30 PM"];
  var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }
  function postForm(action, fields, button, confirmText) {
    var f = el("form", { method: "post", action: action, style: "display:inline;margin:0" });
    if (confirmText) f.setAttribute("data-confirm", confirmText);
    var all = Object.assign({ csrf_token: csrf }, fields);
    Object.keys(all).forEach(function (k) { f.appendChild(el("input", { type: "hidden", name: k, value: all[k] })); });
    f.appendChild(button);
    return f;
  }
  function label(iso) {
    var p = iso.split("-"), d = new Date(+p[0], +p[1] - 1, +p[2]);
    return DAYS[d.getDay()] + " " + (+p[2] < 10 ? "0" : "") + (+p[2]) + " " + MONTHS[+p[1] - 1] + " " + p[0];
  }
  function order(a, b) { return SLOTS.indexOf(a.slot) - SLOTS.indexOf(b.slot); }

  function show(day) {
    var next = location.pathname + "?month=" + encodeURIComponent(month) + "&day=" + day;
    var items = all.filter(function (b) { return b.date === day; }).sort(order);
    var gone = unblocked.filter(function (u) { return u.date === day; }).sort(order);
    title.textContent = label(day);
    body.textContent = "";

    var taken = items.map(function (b) { return b.slot; });
    var whole = taken.indexOf("Full Day") >= 0 || ["7:00 AM", "10:45 AM", "2:30 PM"].every(function (s) { return taken.indexOf(s) >= 0; });
    var free = whole ? [] : ["7:00 AM", "10:45 AM", "2:30 PM"].filter(function (s) { return taken.indexOf(s) < 0; });
    body.appendChild(el("p", { class: "small muted", style: "margin:0 0 .7rem" },
      items.length ? (whole ? "Fully blocked." : "Free: " + free.join(", ") + ".") : "All slots are free."));

    if (items.length) {
      var list = el("ul", { class: "day-list" });
      items.forEach(function (b) {
        var li = el("li");
        var info = el("div", { class: "day-list__info" });
        info.appendChild(el("span", { class: "tag" + (b.slot === "Full Day" ? " tag--debit" : "") }, b.slot));
        var who = [b.by, b.note].filter(Boolean).join(" · ");
        if (who) info.appendChild(el("span", { class: "small" }, " " + who));
        li.appendChild(info);
        if (admin) {
          var acts = el("div", { class: "day-list__acts" });
          var edit = el("button", { type: "button", class: "btn btn--sm btn--ghost", "data-edit-booking": "",
            "data-id": b.id, "data-date": b.date, "data-slot": b.slot, "data-by": b.by, "data-note": b.note }, "Edit");
          acts.appendChild(edit);
          acts.appendChild(postForm(modal.getAttribute("data-delete-base") + b.id + "/delete", { next: next },
            el("button", { type: "submit", class: "btn btn--sm btn--danger" }, "Unblock")));
          li.appendChild(acts);
        }
        list.appendChild(li);
      });
      body.appendChild(list);
      if (admin && items.length >= 2) {
        body.appendChild(postForm(modal.getAttribute("data-day-unblock-url"), { booking_date: day, next: next },
          el("button", { type: "submit", class: "btn btn--sm btn--danger", style: "margin-top:.6rem" }, "Unblock the whole day"),
          "Unblock all " + items.length + " blocks on " + label(day) + "?"));
      }
    }

    if (admin && gone.length) {
      body.appendChild(el("h3", { class: "day-sub" }, "Just unblocked"));
      var undo = el("ul", { class: "day-list" });
      gone.forEach(function (u) {
        var li = el("li");
        var info = el("div", { class: "day-list__info" });
        info.appendChild(el("span", { class: "tag tag--muted" }, u.slot));
        var who = [u.by, u.note].filter(Boolean).join(" · ");
        if (who) info.appendChild(el("span", { class: "small muted" }, " " + who));
        li.appendChild(info);
        li.appendChild(postForm(modal.getAttribute("data-block-url"),
          { booking_date: u.date, slot: u.slot, booked_by: u.by, note: u.note, reblock: "1", next: next },
          el("button", { type: "submit", class: "btn btn--sm" }, "Re-block")));
        undo.appendChild(li);
      });
      body.appendChild(undo);
    }

    if (blockBtn) {
      blockBtn.hidden = whole;
      blockBtn.setAttribute("data-open-block", "");
      blockBtn.setAttribute("data-date", day);
    }
    window.BailsModal.open(modal);
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-day-block]")) { window.BailsModal.close(modal); return; }
    // A free-slot bar inside the cell opens the block dialog instead.
    if (e.target.closest("[data-open-block]")) return;
    var cell = e.target.closest("[data-open-day]");
    if (cell) show(cell.getAttribute("data-date"));
  });
  document.addEventListener("keydown", function (e) {
    var cell = e.target.closest && e.target.closest("[data-open-day]");
    if (cell && e.target === cell && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); show(cell.getAttribute("data-date")); }
  });
  var wanted = new URLSearchParams(location.search).get("day");
  if (wanted && /^\d{4}-\d{2}-\d{2}$/.test(wanted)) show(wanted);
})();

/* Calendar bulk block: build the list (repeat on days, or paste rows), preview
   what will be added or skipped, then save in one go. */
(function () {
  "use strict";
  var form = document.getElementById("bulkForm");
  if (!form) return;
  var box = form.querySelector("[data-bulk-preview]");
  var save = form.querySelector("[data-bulk-save]");
  function mode() { var r = form.querySelector('input[name="mode"]:checked'); return r ? r.value : "repeat"; }
  function syncMode() {
    form.querySelectorAll("[data-bulk-mode]").forEach(function (g) {
      var on = g.getAttribute("data-bulk-mode") === mode();
      g.hidden = !on;
      g.querySelectorAll("input,textarea,select").forEach(function (i) { i.disabled = !on; });
    });
    form.querySelector("#bk-by").placeholder = mode() === "paste"
      ? "Used for rows without an organizer" : "e.g. Octa Legends (Rohit)";
  }
  function stale() { save.disabled = true; save.textContent = "Block"; box.hidden = true; }
  form.addEventListener("change", function (e) {
    if (e.target.name === "mode") syncMode();
    // Full Day and single slots don't mix.
    if (e.target.name === "slot" && e.target.checked) {
      var full = e.target.value === "Full Day";
      form.querySelectorAll('input[name="slot"]').forEach(function (i) {
        if (i !== e.target && (full || i.value === "Full Day")) i.checked = false;
      });
    }
    stale();
  });
  form.addEventListener("input", stale);
  function cell(tr, text, cls) { var td = document.createElement("td"); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); }
  form.querySelector("[data-bulk-check]").addEventListener("click", function () {
    box.hidden = false; box.textContent = "Checking…";
    fetch(form.getAttribute("data-preview-url"), { method: "POST", body: new FormData(form), credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) {
        box.textContent = "";
        (d.problems || []).forEach(function (p) {
          var div = document.createElement("div"); div.className = "small v-neg"; div.textContent = p; box.appendChild(div);
        });
        var skipped = d.rows.length - d.add;
        var head = document.createElement("p");
        head.className = "small"; head.style.margin = ".6rem 0";
        head.textContent = d.rows.length ? d.add + " to block" + (skipped ? ", " + skipped + " skipped (already blocked)" : "") + "."
          : (d.problems && d.problems.length ? "" : "Nothing matches — check the dates, days and slots.");
        box.appendChild(head);
        if (d.rows.length) {
          var wrap = document.createElement("div"); wrap.className = "table-scroll bulk-preview__table";
          var t = document.createElement("table"); t.className = "ledger";
          t.innerHTML = "<thead><tr><th>Date</th><th>Slot</th><th>Booked by</th><th></th></tr></thead>";
          var tb = document.createElement("tbody");
          d.rows.forEach(function (r) {
            var tr = document.createElement("tr");
            if (r.status !== "add") tr.className = "row--muted";
            cell(tr, r.label, "nowrap"); cell(tr, r.slot, "nowrap"); cell(tr, r.by || "—");
            cell(tr, r.status === "add" ? "New" : r.reason, "small " + (r.status === "add" ? "v-pos" : r.status === "clash" ? "v-neg" : "muted"));
            tb.appendChild(tr);
          });
          t.appendChild(tb); wrap.appendChild(t); box.appendChild(wrap);
        }
        save.disabled = !(d.add > 0) || (d.problems && d.problems.length > 0);
        save.textContent = d.add > 0 ? "Block " + d.add + " slot" + (d.add === 1 ? "" : "s") : "Block";
      })
      .catch(function () { box.textContent = "Could not check — are you still signed in?"; });
  });
  document.getElementById("bulkModal").addEventListener("bails:open", function () { syncMode(); stale(); });
  syncMode();
})();
