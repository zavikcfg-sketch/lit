// VPN Admin — фронтовая логика: подтверждения, тосты, прогресс рассылки
(function () {
  "use strict";

  // Подтверждение опасных действий
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm") || "Вы уверены?")) {
        e.preventDefault();
      }
    });
  });

  // Тост-уведомления
  var toast = document.getElementById("toast");
  if (toast) {
    setTimeout(function () {
      toast.style.transition = "opacity .6s";
      toast.style.opacity = "0";
      setTimeout(function () { toast.remove(); }, 700);
    }, 5000);
  }

  // Мобильное меню
  var burger = document.getElementById("burger");
  if (burger) {
    burger.addEventListener("click", function () {
      document.body.classList.toggle("nav-open");
    });
  }

  // Прогресс рассылки (опрос статуса)
  var panel = document.getElementById("bc-panel");
  if (panel) {
    var bar = document.getElementById("bc-progress");
    var text = document.getElementById("bc-text");
    var logEl = document.getElementById("bc-log");
    var stop = false;

    var poll = function () {
      if (stop) return;
      fetch("/broadcast/status", { headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (st) {
          var active = panel.getAttribute("data-active") === "1";
          var changed = false;
          if (active && !st.running && st.total > 0) {
            changed = true; // рассылка завершилась — обновляем страницу
          }
          if (bar) bar.style.width = (st.percent || 0) + "%";
          if (text) {
            text.textContent = st.total
              ? st.sent + "/" + st.total + " отправлено, ошибок: " + st.failed
              : "Рассылок ещё не было.";
          }
          if (logEl && st.log && st.log.length) logEl.textContent = st.log.join("\n");
          if (changed) { stop = true; setTimeout(function () { location.reload(); }, 1500); return; }
          if (st.running) setTimeout(poll, 2000);
        })
        .catch(function () { setTimeout(poll, 4000); });
    };

    if (panel.getAttribute("data-active") === "1") poll();
  }
})();
