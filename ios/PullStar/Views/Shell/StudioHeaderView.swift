import SwiftUI
import PullStarKit

public struct StudioHeaderView: View {
    @Bindable public var model: AppModel

    public init(model: AppModel) {
        self.model = model
    }

    public var body: some View {
        HStack(spacing: 16) {
            // Brand Logo & Title
            HStack(spacing: 10) {
                Image("BrandLogo")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 32, height: 32)
                    .clipShape(Circle())
                    .overlay(Circle().stroke(Color.white.opacity(0.2), lineWidth: 1))
                    .shadow(color: Color.black.opacity(0.4), radius: 4, x: 0, y: 2)

                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 0) {
                        Text("PullStar")
                            .font(.system(size: 19, weight: .semibold, design: .default))
                            .foregroundColor(.psTextPrimary)
                            .tracking(-0.5)
                        Text(".")
                            .font(.system(size: 19, weight: .bold, design: .default))
                            .foregroundColor(Color(hex: 0x929298))
                    }
                    Text("THE NIGHT, IN FOCUS")
                        .font(.system(size: 8, weight: .semibold, design: .default))
                        .foregroundColor(Color(hex: 0x9a9aa0))
                        .tracking(1.8)
                }
            }

            Spacer()

            // Workspace Navigation Pills (visible when results exist)
            if model.hasResult {
                HStack(spacing: 4) {
                    PSButton(
                        "Workspace",
                        systemImage: "square.2.layers.3d",
                        variant: .pill,
                        isActive: model.activeView == .workspace
                    ) {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            model.activeView = .workspace
                        }
                    }

                    PSButton(
                        "Results",
                        systemImage: "checkmark",
                        variant: .pill,
                        isActive: model.activeView == .results
                    ) {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            model.activeView = .results
                        }
                    }
                }
                .padding(4)
                .background(
                    Capsule()
                        .fill(Color.white.opacity(0.04))
                        .overlay(Capsule().stroke(Color.white.opacity(0.1), lineWidth: 1))
                )
            }

            // Status Indicator
            statusBadge
        }
        .padding(.horizontal, 20)
        .frame(height: 58)
        .background(Color.psWorkspaceBg)
        .overlay(alignment: .bottom) {
            Divider().background(Color.white.opacity(0.06))
        }
    }

    private var statusBadge: some View {
        HStack(spacing: 7) {
            if model.isCancelling {
                ProgressView()
                    .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    .scaleEffect(0.7)
                Text("Cancelling…")
                    .font(.psStatus)
                    .foregroundColor(.psTextSecondary)
            } else if model.isProcessing {
                ProgressView()
                    .progressViewStyle(CircularProgressViewStyle(tint: Color(hex: 0x8ec9d1)))
                    .scaleEffect(0.7)
                let pct = Int((model.jobState.overallProgress) * 100)
                Text("Aligning · \(pct)%")
                    .font(.psStatus)
                    .foregroundColor(.psTextSecondary)
            } else if model.jobState.status == .completed {
                LEDIndicator(color: .emerald, size: 6)
                Text("Alignment complete")
                    .font(.psStatus)
                    .foregroundColor(Color(hex: 0xb4b4b9))
            } else if model.jobState.status == .failed {
                Image(systemName: "exclamationmark.circle.fill")
                    .font(.system(size: 12))
                    .foregroundColor(.psDanger)
                Text("Needs attention")
                    .font(.psStatus)
                    .foregroundColor(.psDanger)
            } else if model.jobState.status == .cancelled {
                LEDIndicator(color: .amber, size: 6)
                Text("Alignment cancelled")
                    .font(.psStatus)
                    .foregroundColor(.psTextSecondary)
            } else {
                LEDIndicator(color: .emerald, size: 6)
                Text("Local workspace")
                    .font(.psStatus)
                    .foregroundColor(Color(hex: 0xb4b4b9))
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.white.opacity(0.04))
        )
    }
}
