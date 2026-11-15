/* Revenue forecast chart: actual months solid, forecast months dashed, the
   income 80% range shaded, and a dotted marker where the ground rent starts. */
(function () {
  "use strict";
  var node = document.getElementById("forecastData");
  var canvas = document.getElementById("forecastChart");
  if (!node || !canvas || typeof Chart === "undefined") return;
  var d;
  try { d = JSON.parse(node.textContent); } catch (e) { return; }
  if (!d.labels || !d.labels.length) return;

  function token(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  var cur = document.body.getAttribute("data-currency") || "₹";
  function inr(v) {
    var neg = v < 0, s = String(Math.abs(Math.round(v)));
    if (s.length > 3) {
      var tail = s.slice(-3), head = s.slice(0, -3), g = [];
      while (head.length > 2) { g.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) g.unshift(head);
      s = g.join(",") + "," + tail;
    }
    return (neg ? "-" : "") + cur + s;
  }
  // A segment is dashed once it reaches a month that is not fully actual.
  function dashed(ctx) { return d.status[ctx.p1DataIndex] !== "actual" ? [6, 4] : undefined; }

  var rentMarker = {
    id: "rentMarker",
    afterDatasetsDraw: function (chart) {
      var i = d.labels.indexOf(d.rent_label);
      if (i < 0) return;
      var x = chart.scales.x.getPixelForValue(i), area = chart.chartArea, ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = "#E08A00"; ctx.setLineDash([2, 3]); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle = "#E08A00"; ctx.font = "600 11px system-ui, sans-serif";
      ctx.fillText("Rent", x + 4, area.top + 12);
      ctx.restore();
    }
  };

  var chart;
  function draw() {
    var credit = token("--credit", "#17876A"), debit = token("--debit", "#D72228");
    var ink = token("--ink-muted", "#5B6660"), line = token("--line", "#D3DAD0");
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: d.labels,
        datasets: [
          { label: "Income high", data: d.high, borderWidth: 0, pointRadius: 0, fill: false },
          { label: "Income low", data: d.low, borderWidth: 0, pointRadius: 0,
            fill: "-1", backgroundColor: credit + "22" },
          { label: "Income", data: d.income, borderColor: credit, backgroundColor: credit,
            pointRadius: 2, tension: 0.2, segment: { borderDash: dashed } },
          { label: "Expenses incl. rent", data: d.expenses, borderColor: debit, backgroundColor: debit,
            pointRadius: 2, tension: 0.2, segment: { borderDash: dashed } }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: function (item) { return item.datasetIndex >= 2; },
            callbacks: { label: function (c) { return c.dataset.label + ": " + inr(c.parsed.y); } }
          }
        },
        scales: {
          x: { ticks: { color: ink, maxRotation: 0, autoSkip: true }, grid: { display: false } },
          y: { ticks: { color: ink, callback: function (v) { return inr(v); } }, grid: { color: line } }
        }
      },
      plugins: [rentMarker]
    });
  }
  draw();
  document.addEventListener("bails:themechange", draw);
})();
