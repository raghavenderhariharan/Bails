/* Monthly income / expense / net chart.
   Colours are read from CSS custom properties so light and dark modes use the
   validated steps rather than a hard-coded flip. */
(function () {
  "use strict";

  function readJSON(id, fallback) {
    var node = document.getElementById(id);
    if (!node) return fallback;
    try { return JSON.parse(node.textContent); } catch (e) { return fallback; }
  }

  function token(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  var labels = readJSON("trendData", []);
  var income = readJSON("trendIncome", []);
  var expense = readJSON("trendExpense", []);
  var net = readJSON("trendNet", []);
  var canvas = document.getElementById("trendChart");
  if (!canvas || !labels.length) return;

  var chart = null;

  function currency() {
    return (document.body.getAttribute("data-currency") || "₹");
  }

  function formatINR(value) {
    var negative = value < 0;
    var n = Math.abs(Math.round(value));
    var s = String(n);
    if (s.length > 3) {
      var tail = s.slice(-3);
      var head = s.slice(0, -3);
      var groups = [];
      while (head.length > 2) { groups.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) groups.unshift(head);
      s = groups.join(",") + "," + tail;
    }
    return (negative ? "-" : "") + currency() + s;
  }

  function build() {
    if (chart) chart.destroy();
    if (typeof window.Chart === "undefined") return;

    var credit = token("--credit", "#17876A");
    var debit = token("--debit", "#D72228");
    var netLine = token("--chart-net", "#273076");
    var ink = token("--ink", "#0E1410");
    var ink2 = token("--ink-2", "#4C5852");
    var muted = token("--ink-muted", "#7C8780");
    var grid = token("--grid", "#E4EAE1");
    var surface = token("--surface", "#FFFFFF");

    // netLine comes from --chart-net, which app.css redefines for dark mode,
    // so the plotted line and the HTML legend swatch can never disagree.
    var isDark = document.documentElement.getAttribute("data-theme") === "dark" ||
      (!document.documentElement.getAttribute("data-theme") &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);

    chart = new window.Chart(canvas, {
      data: {
        labels: labels,
        datasets: [
          {
            type: "bar", label: "Income", data: income,
            backgroundColor: credit, borderColor: credit,
            borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
            borderSkipped: false,
            // A 2px surface gap between adjacent bars keeps the pair readable.
            barPercentage: 0.78, categoryPercentage: 0.68,
            order: 2
          },
          {
            type: "bar", label: "Expenses", data: expense,
            backgroundColor: debit, borderColor: debit,
            borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
            borderSkipped: false,
            barPercentage: 0.78, categoryPercentage: 0.68,
            order: 3
          },
          {
            type: "line", label: "Net", data: net,
            borderColor: netLine, backgroundColor: netLine,
            borderWidth: 2, tension: 0.3,
            pointRadius: 4, pointHoverRadius: 7,
            pointBackgroundColor: netLine,
            // A 2px surface ring keeps the markers legible where they overlap bars.
            pointBorderColor: surface, pointBorderWidth: 2,
            order: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: isDark ? "#1F2634" : "#10231A",
            titleColor: "#fff", bodyColor: "#fff",
            padding: 10, cornerRadius: 8, displayColors: true, boxPadding: 4,
            callbacks: {
              label: function (ctx) { return ctx.dataset.label + ": " + formatINR(ctx.parsed.y); }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: grid },
            ticks: { color: muted, font: { size: 11 } }
          },
          y: {
            beginAtZero: true,
            grid: { color: grid, drawTicks: false },
            border: { display: false },
            ticks: {
              color: muted, font: { size: 11 }, padding: 8,
              callback: function (value) { return formatINR(value); }
            }
          }
        }
      }
    });
  }

  function boot() {
    if (typeof window.Chart !== "undefined") { build(); return; }
    // chart.umd.min.js is deferred; wait for it rather than racing it.
    var tries = 0;
    var timer = setInterval(function () {
      if (typeof window.Chart !== "undefined") { clearInterval(timer); build(); }
      else if (++tries > 40) { clearInterval(timer); }
    }, 50);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.addEventListener("bails:themechange", build);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
    if (!document.documentElement.getAttribute("data-theme")) build();
  });
})();
