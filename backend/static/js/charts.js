(function () {
  const instances = new Map();
  const locale = document.documentElement.lang || navigator.language || "ru-RU";

  function destroyIfExists(canvasId) {
    const existing = instances.get(canvasId);
    if (existing) {
      existing.destroy();
      instances.delete(canvasId);
    }
  }

  function formatNumber(value, options) {
    const num = Number(value || 0);
    const fractionDigits = Number.isInteger(num) ? 0 : 2;

    if (options && options.isPercent) {
      return `${new Intl.NumberFormat(locale, {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: 2,
      }).format(num)}%`;
    }

    if (options && options.currencyCode) {
      return new Intl.NumberFormat(locale, {
        style: "currency",
        currency: options.currencyCode,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(num);
    }

    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: 2,
    }).format(num);
  }

  function baseOptions(yTitle, formatOptions) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: 450,
      },
      interaction: {
        mode: "index",
        intersect: false,
      },
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: {
            color: "#cbd5e1",
            boxWidth: 14,
          },
        },
        tooltip: {
          backgroundColor: "rgba(15, 23, 42, 0.95)",
          borderColor: "#334155",
          borderWidth: 1,
          titleColor: "#f1f5f9",
          bodyColor: "#f1f5f9",
          callbacks: {
            label: function (context) {
              const label = context.dataset.label ? `${context.dataset.label}: ` : "";
              return `${label}${formatNumber(context.parsed.y, formatOptions)}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: {
            color: "rgba(51, 65, 85, 0.25)",
          },
          ticks: {
            color: "#94a3b8",
            maxRotation: 50,
            minRotation: 0,
            autoSkip: true,
            maxTicksLimit: 12,
          },
        },
        y: {
          beginAtZero: true,
          grid: {
            color: "rgba(51, 65, 85, 0.35)",
          },
          ticks: {
            color: "#94a3b8",
            callback: function (value) {
              return formatNumber(value, formatOptions);
            },
          },
          title: {
            display: Boolean(yTitle),
            text: yTitle || "",
            color: "#cbd5e1",
          },
        },
      },
    };
  }

  function renderBarChart(canvasId, config) {
    const el = document.getElementById(canvasId);
    if (!el || typeof Chart === "undefined") {
      return;
    }
    destroyIfExists(canvasId);

    const labels = Array.isArray(config.labels) ? config.labels : [];
    const values = Array.isArray(config.values) ? config.values : [];

    const chart = new Chart(el, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: config.label || "Series",
            data: values,
            backgroundColor: config.color || "#38bdf8",
            borderColor: config.borderColor || "#0ea5e9",
            borderWidth: 1,
            borderRadius: 6,
            maxBarThickness: 30,
          },
        ],
      },
      options: baseOptions(config.yTitle, {
        currencyCode: config.currencyCode || "",
        isPercent: Boolean(config.isPercent),
      }),
    });

    instances.set(canvasId, chart);
  }

  function renderLineChart(canvasId, config) {
    const el = document.getElementById(canvasId);
    if (!el || typeof Chart === "undefined") {
      return;
    }
    destroyIfExists(canvasId);

    const labels = Array.isArray(config.labels) ? config.labels : [];
    const values = Array.isArray(config.values) ? config.values : [];

    const chart = new Chart(el, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: config.label || "Series",
            data: values,
            borderColor: config.color || "#22d3ee",
            backgroundColor: config.fillColor || "rgba(34, 211, 238, 0.15)",
            borderWidth: 3,
            pointRadius: 3,
            pointHoverRadius: 5,
            pointBackgroundColor: config.pointColor || config.color || "#22d3ee",
            fill: true,
            tension: 0.3,
          },
        ],
      },
      options: baseOptions(config.yTitle, {
        currencyCode: config.currencyCode || "",
        isPercent: Boolean(config.isPercent),
      }),
    });

    instances.set(canvasId, chart);
  }

  window.QueueCharts = {
    renderBarChart,
    renderLineChart,
  };
})();
