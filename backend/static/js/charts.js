(function () {
  const instances = new Map();
  const locale = document.documentElement.lang || navigator.language || "ru-RU";
  const numberFormatCache = new Map();

  function getFormatter(options) {
    const key = JSON.stringify(options || {});
    if (!numberFormatCache.has(key)) {
      numberFormatCache.set(key, new Intl.NumberFormat(locale, options || {}));
    }
    return numberFormatCache.get(key);
  }

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
      return `${getFormatter({
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: 2,
      }).format(num)}%`;
    }

    if (options && options.currencyCode) {
      return getFormatter({
        style: "currency",
        currency: options.currencyCode,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(num);
    }

    return getFormatter({
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: 2,
    }).format(num);
  }

  function baseOptions(yTitle, formatOptions, pointCount) {
    const largeDataset = (pointCount || 0) > 120;
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: largeDataset ? 0 : 450,
      },
      interaction: {
        mode: "index",
        intersect: false,
      },
      parsing: false,
      normalized: true,
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
      elements: {
        point: {
          radius: largeDataset ? 0 : 3,
          hoverRadius: largeDataset ? 3 : 5,
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

  function downsampleSeries(labels, values, maxPoints) {
    if (!Array.isArray(labels) || !Array.isArray(values)) {
      return { labels: [], values: [] };
    }
    const size = Math.min(labels.length, values.length);
    if (size <= maxPoints) {
      return { labels: labels.slice(0, size), values: values.slice(0, size) };
    }
    const sampledLabels = [];
    const sampledValues = [];
    const step = (size - 1) / (maxPoints - 1);
    for (let i = 0; i < maxPoints; i += 1) {
      const idx = Math.round(i * step);
      sampledLabels.push(labels[idx]);
      sampledValues.push(values[idx]);
    }
    return { labels: sampledLabels, values: sampledValues };
  }

  function renderWhenVisible(el, renderFn) {
    if (!("IntersectionObserver" in window)) {
      renderFn();
      return;
    }
    if (el.dataset.chartObserved === "1") {
      return;
    }
    el.dataset.chartObserved = "1";
    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            observer.disconnect();
            renderFn();
          }
        });
      },
      { rootMargin: "200px 0px" }
    );
    observer.observe(el);
  }

  function renderBarChart(canvasId, config) {
    const el = document.getElementById(canvasId);
    if (!el || typeof Chart === "undefined") {
      return;
    }

    renderWhenVisible(el, function () {
      destroyIfExists(canvasId);

      const labels = Array.isArray(config.labels) ? config.labels : [];
      const values = Array.isArray(config.values) ? config.values : [];
      const sampled = downsampleSeries(labels, values, Number(config.maxPoints || 180));

      const chart = new Chart(el, {
        type: "bar",
        data: {
          labels: sampled.labels,
          datasets: [
            {
              label: config.label || "Series",
              data: sampled.values,
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
        }, sampled.values.length),
      });

      instances.set(canvasId, chart);
    });
  }

  function renderLineChart(canvasId, config) {
    const el = document.getElementById(canvasId);
    if (!el || typeof Chart === "undefined") {
      return;
    }

    renderWhenVisible(el, function () {
      destroyIfExists(canvasId);

      const labels = Array.isArray(config.labels) ? config.labels : [];
      const values = Array.isArray(config.values) ? config.values : [];
      const sampled = downsampleSeries(labels, values, Number(config.maxPoints || 240));

      const chart = new Chart(el, {
        type: "line",
        data: {
          labels: sampled.labels,
          datasets: [
            {
              label: config.label || "Series",
              data: sampled.values,
              borderColor: config.color || "#22d3ee",
              backgroundColor: config.fillColor || "rgba(34, 211, 238, 0.15)",
              borderWidth: 3,
              pointBackgroundColor: config.pointColor || config.color || "#22d3ee",
              fill: true,
              tension: 0.3,
            },
          ],
        },
        options: baseOptions(config.yTitle, {
          currencyCode: config.currencyCode || "",
          isPercent: Boolean(config.isPercent),
        }, sampled.values.length),
      });

      instances.set(canvasId, chart);
    });
  }

  window.QueueCharts = {
    renderBarChart,
    renderLineChart,
  };
})();
