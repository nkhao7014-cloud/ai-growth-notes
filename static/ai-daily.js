(() => {
  const baseSetView = window.setView;
  const topNav = document.querySelector(".tabs");
  const bottomNav = document.querySelector(".bottom-nav");
  const dashboardSide = document.querySelector(".dashboard-side");
  const dailyView = document.getElementById("ai-dailyView");

  const topButton = document.createElement("button");
  topButton.className = "tab nav-tab";
  topButton.type = "button";
  topButton.dataset.view = "ai-daily";
  topButton.innerHTML = '<span class="tab-icon" aria-hidden="true">✦</span>AI Daily';
  topNav.insertBefore(topButton, topNav.children[1]);

  const bottomButton = document.createElement("button");
  bottomButton.className = "bottom-nav-item";
  bottomButton.type = "button";
  bottomButton.dataset.view = "ai-daily";
  bottomButton.innerHTML = '<span aria-hidden="true">✦</span>AI Daily';
  bottomNav.insertBefore(bottomButton, bottomNav.children[1]);

  const entry = document.createElement("section");
  entry.className = "card app-card ai-daily-entry";
  entry.innerHTML = '<div class="eyebrow">Daily Briefing</div><h3>AI Daily</h3><p>今日のAI学習情報を確認する</p><button class="primary action-button" type="button">Open AI Daily</button>';
  dashboardSide.appendChild(entry);

  function showView(name, updateHistory = true) {
    baseSetView(name);
    const path = name === "ai-daily" ? "/ai-daily" : "/";
    if (updateHistory && location.pathname !== path) history.pushState({view: name}, "", path);
    document.title = name === "ai-daily" ? "AI Daily | AI Growth Notes" : "AI Growth Notes";
  }

  document.querySelectorAll("[data-view]").forEach(button => {
    button.onclick = () => showView(button.dataset.view);
  });
  entry.querySelector("button").onclick = () => showView("ai-daily");

  function showToast(message) {
    let toast = document.getElementById("aiDailyToast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "aiDailyToast";
      toast.className = "ai-daily-toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("show"), 2400);
  }

  async function loadDaily() {
    try {
      const response = await fetch("/static/ai-daily-content.html");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      dailyView.innerHTML = await response.text();
      const now = new Date();
      const formatter = new Intl.DateTimeFormat("ja-JP", {year:"numeric", month:"long", day:"numeric", weekday:"short"});
      document.getElementById("aiDailyDate").textContent = formatter.format(now);
      const updated = document.getElementById("aiDailyUpdated");
      updated.dateTime = now.toISOString();
      updated.textContent = `最終更新 ${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}`;
      document.getElementById("aiDailyRefresh").onclick = event => {
        const button = event.currentTarget;
        button.disabled = true;
        button.classList.add("is-loading");
        button.textContent = "更新中…";
        setTimeout(() => {
          button.disabled = false;
          button.classList.remove("is-loading");
          button.textContent = "更新する";
          showToast("Sprint 1ではダミーデータを表示しています");
        }, 800);
      };
      dailyView.querySelectorAll("[data-demo-action]").forEach(button => {
        button.onclick = () => showToast("この機能はSprint 2以降で実装予定です");
      });
    } catch (error) {
      dailyView.innerHTML = `<section class="card app-card"><h2>AI Daily</h2><p>画面を読み込めませんでした: ${error.message}</p></section>`;
    }
  }

  loadDaily().then(() => {
    if (location.pathname === "/ai-daily") showView("ai-daily", false);
  });
  window.addEventListener("popstate", () => showView(location.pathname === "/ai-daily" ? "ai-daily" : "dashboard", false));
})();
