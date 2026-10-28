import { BrowserRouter } from "react-router";
import { AppShell } from "./layout/AppShell";
import { ThemeProvider } from "./themes/ThemeProvider";

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </ThemeProvider>
  );
}
