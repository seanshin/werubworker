import { Component, type ReactNode } from "react";
import i18n from "../i18n";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="p-4 text-center text-muted">
          <p className="text-[13px]">{i18n.t("common:error.somethingWrong")}</p>
          <button
            className="mt-2 text-[12px] text-accent hover:underline"
            onClick={() => this.setState({ hasError: false })}
          >
            {i18n.t("common:error.tryAgain")}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
