import "@fontsource-variable/manrope/wght.css";
import "@fontsource-variable/jetbrains-mono/wght.css";
import "./app.css";
import "./forms.css";
import "./responsive.css";
import { mount } from "svelte";
import App from "./App.svelte";

const target = document.getElementById("app");

if (!target) {
  throw new Error("Application mount point is missing");
}

const app = mount(App, { target });

export default app;
