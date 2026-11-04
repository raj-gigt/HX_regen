# Kern shell-side j_h chart digitisation

**Source:** user-uploaded image `Kern_shell_side_jh_Fig9_user_supplied.png`, titled “Fig. 9: Shell-side heat-transfer factors, segmental baffles”.

The chart contains four segmental-baffle curves, labelled 15%, 25%, 35%, and 45% (top to bottom). The rating applications use a lookup table digitised approximately from the displayed graph. Reynolds number is interpolated log-log between digitised locations; baffle cut is linearly interpolated between curves when the entered value is between source curves. The GUI accepts a baffle-cut percentage from 10% to 45%; the four source curves are used directly at 15%, 25%, 35%, and 45%, with linear interpolation between curves for intermediate values. Below 15%, the 15% curve is used and a warning is included.

Chart axes used for digitisation: plot x approximately 199–1317 px, covering Re=10 to 10^6. The left j_h axis spans 10^0 to 10^-3; the right j_h axis spans 10^-2 to 10^-5. Pixel readings and interpolation introduce chart-reading uncertainty. The values are not exact manufacturer/tabulated data.

The code uses this chart only in the existing Kern single-phase shell-side service calculation. It does not extend Kern's single-phase chart to two-phase shell-side crossflow.
