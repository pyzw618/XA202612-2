export {};

declare global {
  interface Window {
    memoryHubDesktop?: {
      getRuntime(): Promise<{
        desktop: true;
        platform: string;
        arch: string;
        appVersion: string;
        backend: DesktopBackendStatus;
      }>;
      checkBackend(): Promise<DesktopBackendStatus>;
      openApiDocs(): Promise<boolean>;
    };
  }

  interface DesktopBackendStatus {
    online: boolean;
    backendUrl: string;
    latencyMs: number;
    checkedAt: string;
    message?: string;
  }
}
