| model_name | row_count | brier_score | brier_delta_vs_raw | log_loss | log_loss_delta_vs_raw | expected_calibration_error | ece_delta_vs_raw | calibration_intercept | calibration_slope | calibration_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| raw | 492612 | 0.1005 | 0.0000 | 0.3188 | 0.0000 | 0.0121 | 0.0000 | -0.0659 | 1.0779 | converged |
| platt | 492612 | 0.1003 | -0.0002 | 0.3178 | -0.0010 | 0.0018 | -0.0103 | -0.0164 | 1.0045 | converged |
| beta | 492612 | 0.1003 | -0.0002 | 0.3178 | -0.0010 | 0.0027 | -0.0094 | -0.0166 | 1.0053 | converged |
| isotonic | 492612 | 0.1004 | -0.0000 | 0.3239 | 0.0052 | 0.0055 | -0.0066 | 0.0268 | 0.9910 | converged |
