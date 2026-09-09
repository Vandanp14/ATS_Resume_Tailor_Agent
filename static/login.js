"use strict";
document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("sign-in");
  if (button.disabled) return;
  const error = document.getElementById("login-error");
  button.disabled = true;
  button.textContent = "Signing in…";
  error.textContent = "";
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: document.getElementById("password").value }),
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(typeof body.detail === "string" ? body.detail : "Sign in failed. Try again.");
    }
    location.replace("/");
  } catch (cause) {
    error.textContent = cause.name === "TimeoutError" ? "Connection timed out. Try again." : cause.message;
  } finally {
    button.disabled = false;
    button.textContent = "Sign in";
  }
});
