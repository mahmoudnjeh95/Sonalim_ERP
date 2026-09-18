import type { SVGProps } from "react";
import LoadingSpinner from "../../assets/animations/status/loading-spinner.svg?react";
import SyncIcon from "../../assets/animations/status/sync.svg?react";
import ProcessingIcon from "../../assets/animations/status/processing.svg?react";
import MachineRunningIcon from "../../assets/animations/status/machine-running.svg?react";
import SuccessIcon from "../../assets/animations/status/success.svg?react";
import WarningIcon from "../../assets/animations/status/warning.svg?react";
import ErrorIcon from "../../assets/animations/status/error.svg?react";

const statusMap = {
  loading: LoadingSpinner,
  syncing: SyncIcon,
  processing: ProcessingIcon,
  machine: MachineRunningIcon,
  success: SuccessIcon,
  warning: WarningIcon,
  error: ErrorIcon,
} as const;

type StatusType = keyof typeof statusMap;

interface StatusAnimationProps extends SVGProps<SVGSVGElement> {
  type: StatusType;
  size?: number;
}

export function StatusAnimation({ type, size = 64, ...props }: StatusAnimationProps) {
  const Icon = statusMap[type];

  return <Icon width={size} height={size} {...props} />;
}
