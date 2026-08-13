import Evidence from "./Evidence";
import Home from "./Home";

export default function App() {
  const base = import.meta.env.BASE_URL;
  const relativePath = window.location.pathname.startsWith(base)
    ? window.location.pathname.slice(base.length)
    : window.location.pathname;

  return relativePath.replace(/^\/+/, "").startsWith("evidence") ? <Evidence /> : <Home />;
}
