| model_name | row_count | brier_score | brier_delta_vs_raw | log_loss | log_loss_delta_vs_raw | expected_calibration_error | ece_delta_vs_raw | calibration_intercept | calibration_slope | calibration_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| raw | 409 | 0.1030 | 0.0000 | 0.3290 | 0.0000 | 0.0567 | 0.0000 | 0.5720 | 1.4851 | converged |
| platt | 409 | 0.1023 | -0.0007 | 0.3239 | -0.0051 | 0.0557 | -0.0009 | 0.5545 | 1.3373 | converged |
| beta | 409 | 0.1024 | -0.0006 | 0.3241 | -0.0048 | 0.0569 | 0.0002 | 0.5450 | 1.3357 | converged |
| isotonic | 409 | 0.1023 | -0.0008 | 0.3234 | -0.0056 | 0.0453 | -0.0113 | 0.4620 | 1.2424 | converged |
