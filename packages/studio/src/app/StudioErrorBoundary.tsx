import { Component, type ErrorInfo, type ReactNode } from "react";

interface BoundaryState {
  error?: Error;
}

interface StudioErrorBoundaryProps {
  children: ReactNode;
  editorUrl: string;
}

export class StudioErrorBoundary extends Component<StudioErrorBoundaryProps, BoundaryState> {
  override state: BoundaryState = {};

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Studio could not render", error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (error) {
      return (
        <main className="studio-startup-error" role="alert">
          <strong>Studio could not open</strong>
          <p>{error.message}</p>
          <a className="studio-native-editor-link" href={this.props.editorUrl}>
            Open the Marimo editor
          </a>
        </main>
      );
    }
    return this.props.children;
  }
}
