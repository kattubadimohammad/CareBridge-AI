// CareBridge AI - Client Accessibility & Interaction Helpers

document.addEventListener("DOMContentLoaded", () => {
  // Live Clock for senior clarity
  const clockElement = document.getElementById("live-clock");
  if (clockElement) {
    const updateClock = () => {
      const now = new Date();
      clockElement.textContent = now.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    };
    updateClock();
    setInterval(updateClock, 1000);
  }
});
