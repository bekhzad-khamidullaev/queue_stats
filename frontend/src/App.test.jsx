import { render, screen } from "@testing-library/react";
import App from "./App";

vi.mock("./context/AuthContext.jsx", () => ({
  useAuth: () => ({
    user: null,
    loading: true,
    logout: vi.fn(),
  }),
}));

vi.mock("./hooks/useMetaData.js", () => ({
  default: () => ({
    queues: [],
    agents: [],
    loading: false,
    error: null,
  }),
}));

describe("App", () => {
  it("renders auth loading state", () => {
    render(<App />);
    expect(screen.getByText("Asterisk Queue Stats")).toBeInTheDocument();
    expect(screen.getByText("Проверяем сессию…")).toBeInTheDocument();
  });
});
