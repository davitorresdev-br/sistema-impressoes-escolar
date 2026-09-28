
  import { createRoot } from "react-dom/client";
  import App from "./app/App.tsx";
  // @ts-ignore: Allow importing CSS without type declarations
  import "./styles/index.css";

  createRoot(document.getElementById("root")!).render(<App />);
  