// The desktop shell passes the private backend's dynamically allocated address.
const backendOrigin = window.starAligner?.apiOrigin ?? "http://127.0.0.1:8000";
export const API_ORIGIN = import.meta.env.DEV ? "" : backendOrigin;
export const WS_ORIGIN = import.meta.env.DEV
  ? window.location.origin.replace(/^http/, "ws")
  : backendOrigin.replace(/^http/, "ws");
