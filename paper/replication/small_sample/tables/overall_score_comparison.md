| model_name | row_count | brier_score | brier_delta_vs_raw | log_loss | log_loss_delta_vs_raw | expected_calibration_error | ece_delta_vs_raw | calibration_intercept | calibration_slope | calibration_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| raw | 409 | 0.1030 | 0.0000 | 0.3290 | 0.0000 | 0.0567 | 0.0000 | 0.5720 | 1.4851 | converged |
| platt | 409 | 0.1023 | -0.0007 | 0.3238 | -0.0052 | 0.0635 | 0.0068 | 0.5471 | 1.3400 | converged |
| beta | 409 | 0.1024 | -0.0006 | 0.3242 | -0.0048 | 0.0570 | 0.0003 | 0.5375 | 1.3391 | converged |
| isotonic | 409 | 0.1021 | -0.0009 | 0.3229 | -0.0060 | 0.0453 | -0.0113 | 0.4477 | 1.2381 | converged |
