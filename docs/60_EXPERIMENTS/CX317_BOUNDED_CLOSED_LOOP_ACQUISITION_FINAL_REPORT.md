# CX317 Bounded Closed-Loop Acquisition Programme Final Review

Decision: `dual_core_frequency_control_endurance_passed`.

## Rationale

Both single-core acquisition campaigns, dual-core isolation, composite active confirmation and the bounded 24-hour endurance gate pass with exact replay.

## Exit-gate audit

| Gate | Result | Evidence / SHA-256 |
| --- | --- | --- |
| campaign_a | pass | e981fae26b912d590f79c1a05bfa54c7f70b8d013fb1ba57e80bfeb79eeb93bf |
| campaign_b | pass | 9a56c6d5d7e2eb287f60df23f56b401ea55831eeccbcaa3fcdabbf6c5e31c607 |
| stage6 | pass | 00c940aa3b656fa66d216201c4ffaf0bb49d9f8587725f0bccbd987c2795d040 |
| stage7_a1 | pass | e7ee752ce6994f7e00c3a512167764f60c1bd81578b37576dd02e817b403831f |
| stage7_a2 | pass | e76ce2edf27ae5d28228ebcc6a7ca3e9d229a9c0c8c4f7b904a0b14a51606133 |
| stage7_b | pass | e9138a05bb1dd0f88842e539ecdfc695b681e31c6311d41f4e1b1c4124fa9668 |
| verification | pass | 15f126542c20915da823b37b28daf5e09d05b74002a5386cd689c86d063e146c |
| campaign_a_sealed_run | pass | run campaign_a_v3_20260803T183120Z; COMPLETE=True; capture_active=False; snapshot 8cea3ec7b37e65969f9ed0b37b5970627e91b97e5265a54316bbb24b656e4fbb; gate_in_snapshot=True; gate SHA-256 e981fae26b912d590f79c1a05bfa54c7f70b8d013fb1ba57e80bfeb79eeb93bf; failures=0 |
| campaign_b_sealed_run | pass | run campaign_b_20260804T022822Z; COMPLETE=True; capture_active=False; snapshot ddc98475b2ef09a8f9dfeb669feefbf76756615e219ed0b83209597e8a340bf7; gate_in_snapshot=True; gate SHA-256 9a56c6d5d7e2eb287f60df23f56b401ea55831eeccbcaa3fcdabbf6c5e31c607; failures=0 |
| stage6_sealed_run | pass | run dual_core_live_v3_20260804T110756Z; COMPLETE=True; capture_active=False; snapshot 666761e143601f7fa6cefb400c4909d018b2819d7a48f82aae7fe64785622925; gate_in_snapshot=False; gate SHA-256 00c940aa3b656fa66d216201c4ffaf0bb49d9f8587725f0bccbd987c2795d040; failures=0 |
| stage7_a1_transitively_sealed_subtest | pass | A1 SHA-256 e7ee752ce6994f7e00c3a512167764f60c1bd81578b37576dd02e817b403831f; Part B binding=True; failures=0 |
| stage7_a2_composite_sealed_evidence | pass | composite SHA-256 e76ce2edf27ae5d28228ebcc6a7ca3e9d229a9c0c8c4f7b904a0b14a51606133; components=3/3; Part B binding=True; failures=0 |
| stage7_b_sealed_run | pass | run part_b_final_20260807T073432Z; COMPLETE=True; capture_active=False; snapshot 7f862ee45b849d0149b4a7fe3b0744e7ad6472fcbefed817d92f2afcf4a22d23; gate_in_snapshot=True; gate SHA-256 e9138a05bb1dd0f88842e539ecdfc695b681e31c6311d41f4e1b1c4124fa9668; failures=0 |

## Immutable run seals

| Gate | Seal class | Snapshot digest | Gate in snapshot |
| --- | --- | --- | --- |
| campaign_a | complete_run | 8cea3ec7b37e65969f9ed0b37b5970627e91b97e5265a54316bbb24b656e4fbb | True |
| campaign_b | complete_run | ddc98475b2ef09a8f9dfeb669feefbf76756615e219ed0b83209597e8a340bf7 | True |
| stage6 | complete_run | 666761e143601f7fa6cefb400c4909d018b2819d7a48f82aae7fe64785622925 | False |
| stage7_a1 | part_b_manifest_bound_validated_partial_a1_subtest | b83737f687ebf554058da1654a1f56090dac86d77509dae0bce79a6e0bdeb72c | False |
| stage7_a2 | part_b_manifest_bound_composite_of_validated_source_seals | transitive_component_seals | False |
| stage7_b | complete_run | 7f862ee45b849d0149b4a7fe3b0744e7ad6472fcbefed817d92f2afcf4a22d23 | True |

## Active-run correction history

| Run | Stage | Terminal | Automatic corrections | Movement (codes) | Final code | Evidence state |
| --- | --- | --- | --- | --- | --- | --- |
| campaign_a_20260803T125400Z | CX317_BOUNDED_ACTIVE_CAMPAIGN_A | fault | 1 | 21 | 0xA93B | partial |
| campaign_a_v2_20260803T170039Z | CX317_BOUNDED_ACTIVE_CAMPAIGN_A | aborted | 1 | 21 | 0xA93B | partial |
| campaign_a_v3_20260803T183120Z | CX317_BOUNDED_ACTIVE_CAMPAIGN_A | healthy_stop | 12 | 250 | 0xA856 | complete |
| device_abort_smoke_20260803T125100Z | CX317_BOUNDED_ACTIVE_CAMPAIGN_A | aborted | 0 | 0 | unavailable | partial |
| out_of_model_passive_a93b_20260803T140906Z | CX317_OUT_OF_MODEL_PASSIVE_OBSERVATION | unavailable | 0 | 0 | unavailable | missing |
| rapid_step_characterization_20260803T141658Z | CX317_PPS_GATED_OPEN_LOOP | unavailable | 0 | 0 | 0xA950 | complete |
| campaign_b_20260804T022822Z | CX317_BOUNDED_ACTIVE_CAMPAIGN_B | healthy_stop | 2 | 42 | 0xA82A | complete |
| active_hil_rehearsal_v3_20260807T061811Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | aborted | 0 | 0 | unavailable | partial |
| active_hil_rehearsal_v4_20260807T062941Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | aborted | 0 | 0 | unavailable | missing |
| active_hil_rehearsal_v5_20260807T064546Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | aborted | 0 | 0 | 0xA800 | partial |
| active_hil_rehearsal_v6_20260807T065805Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | healthy_stop | 2 | 42 | 0xA82A | complete |
| part_a2_20260805T065551Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA800 | partial |
| part_a2_20260805T084537Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA800 | partial |
| part_a2_20260805T090847Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 1 | 21 | 0xA815 | partial |
| part_a2_20260805T113912Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 1 | 21 | 0xA815 | partial |
| part_a_20260804T142912Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | unavailable | missing |
| part_a_20260804T150342Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA82A | missing |
| part_a_20260804T161646Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA82A | missing |
| part_a_20260804T174201Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA82A | missing |
| part_a_20260804T191214Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA82A | missing |
| part_a_20260804T204214Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA82A | missing |
| part_a_20260804T222508Z | CX317_DUAL_CORE_ACTIVE_PART_A | aborted | 0 | 0 | 0xA82A | partial |
| part_b_20260805T140241Z | CX317_DUAL_CORE_ACTIVE_PART_B | aborted | 1 | 19 | 0xA828 | partial |
| part_b_final_20260807T073432Z | CX317_DUAL_CORE_ACTIVE_PART_B | healthy_stop | 1 | 19 | 0xA828 | complete |
| part_b_retry_20260806T050640Z | CX317_DUAL_CORE_ACTIVE_PART_B | aborted | 1 | 19 | 0xA828 | partial |
| rehearsal_20260805T104402Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | aborted | 0 | 0 | 0xA800 | partial |
| rehearsal_service_arm_20260806T042537Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | healthy_stop | 2 | 42 | 0xA82A | complete |
| rehearsal_v2_20260805T111805Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | aborted | 0 | 0 | unavailable | partial |
| rehearsal_v3_20260805T112524Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | healthy_stop | 1 | 21 | 0xA815 | complete |
| rehearsal_v4_20260805T131900Z | CX317_STAGE7_DIAGNOSTIC_REHEARSAL | healthy_stop | 2 | 42 | 0xA82A | complete |
| transport_fault_rehearsal_20260807T010100Z | CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL | unavailable | 0 | 0 | unavailable | missing |
| transport_fault_rehearsal_20260807T061524Z | CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL | aborted | 0 | 0 | unavailable | complete |
| transport_fault_rehearsal_v2_20260807T062625Z | CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL | aborted | 0 | 0 | unavailable | complete |
| transport_fault_rehearsal_v3_20260807T064240Z | CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL | unavailable | 0 | 0 | unavailable | missing |
| transport_fault_rehearsal_v4_20260807T064359Z | CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL | aborted | 0 | 0 | unavailable | complete |
| transport_fault_rehearsal_v5_20260807T065642Z | CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL | aborted | 0 | 0 | unavailable | complete |

### Exact automatic applications

| Run | Request | Delta | Requested | Applied | Pre-error (Hz) |
| --- | --- | --- | --- | --- | --- |
| campaign_a_20260803T125400Z | 1 | -21 | 0xA93B | 0xA93B | 0.045 |
| campaign_a_v2_20260803T170039Z | 1 | -21 | 0xA93B | 0xA93B | 0.045 |
| campaign_a_v3_20260803T183120Z | 1 | -21 | 0xA93B | 0xA93B | 0.046666667 |
| campaign_a_v3_20260803T183120Z | 2 | -21 | 0xA926 | 0xA926 | 0.041666666 |
| campaign_a_v3_20260803T183120Z | 3 | -21 | 0xA911 | 0xA911 | 0.038333334 |
| campaign_a_v3_20260803T183120Z | 4 | -21 | 0xA8FC | 0xA8FC | 0.035 |
| campaign_a_v3_20260803T183120Z | 5 | -21 | 0xA8E7 | 0xA8E7 | 0.031666666 |
| campaign_a_v3_20260803T183120Z | 6 | -21 | 0xA8D2 | 0xA8D2 | 0.028333334 |
| campaign_a_v3_20260803T183120Z | 7 | -21 | 0xA8BD | 0xA8BD | 0.025 |
| campaign_a_v3_20260803T183120Z | 8 | -21 | 0xA8A8 | 0xA8A8 | 0.021666666 |
| campaign_a_v3_20260803T183120Z | 9 | -21 | 0xA893 | 0xA893 | 0.016666668 |
| campaign_a_v3_20260803T183120Z | 10 | -21 | 0xA87E | 0xA87E | 0.015000001 |
| campaign_a_v3_20260803T183120Z | 11 | -21 | 0xA869 | 0xA869 | 0.01 |
| campaign_a_v3_20260803T183120Z | 12 | -19 | 0xA856 | 0xA856 | 0.006666666 |
| device_abort_smoke_20260803T125100Z | none | 0 | — | — | — |
| out_of_model_passive_a93b_20260803T140906Z | none | 0 | — | — | — |
| rapid_step_characterization_20260803T141658Z | none | 0 | — | — | — |
| campaign_b_20260804T022822Z | 1 | 21 | 0xA815 | 0xA815 | -0.011666667 |
| campaign_b_20260804T022822Z | 2 | 21 | 0xA82A | 0xA82A | -0.008333333 |
| active_hil_rehearsal_v3_20260807T061811Z | none | 0 | — | — | — |
| active_hil_rehearsal_v4_20260807T062941Z | none | 0 | — | — | — |
| active_hil_rehearsal_v5_20260807T064546Z | none | 0 | — | — | — |
| active_hil_rehearsal_v6_20260807T065805Z | 1 | 21 | 0xA815 | 0xA815 | -0.008333333 |
| active_hil_rehearsal_v6_20260807T065805Z | 2 | 21 | 0xA82A | 0xA82A | -0.008333333 |
| part_a2_20260805T065551Z | none | 0 | — | — | — |
| part_a2_20260805T084537Z | none | 0 | — | — | — |
| part_a2_20260805T090847Z | 1 | 21 | 0xA815 | 0xA815 | -0.011666667 |
| part_a2_20260805T113912Z | 1 | 21 | 0xA815 | 0xA815 | -0.01 |
| part_a_20260804T142912Z | none | 0 | — | — | — |
| part_a_20260804T150342Z | none | 0 | — | — | — |
| part_a_20260804T161646Z | none | 0 | — | — | — |
| part_a_20260804T174201Z | none | 0 | — | — | — |
| part_a_20260804T191214Z | none | 0 | — | — | — |
| part_a_20260804T204214Z | none | 0 | — | — | — |
| part_a_20260804T222508Z | none | 0 | — | — | — |
| part_b_20260805T140241Z | 1 | 19 | 0xA828 | 0xA828 | -0.006666666 |
| part_b_final_20260807T073432Z | 1 | 19 | 0xA828 | 0xA828 | -0.006666666 |
| part_b_retry_20260806T050640Z | 1 | 19 | 0xA828 | 0xA828 | -0.006666666 |
| rehearsal_20260805T104402Z | none | 0 | — | — | — |
| rehearsal_service_arm_20260806T042537Z | 1 | 21 | 0xA815 | 0xA815 | -0.016666668 |
| rehearsal_service_arm_20260806T042537Z | 2 | 21 | 0xA82A | 0xA82A | -0.008333333 |
| rehearsal_v2_20260805T111805Z | none | 0 | — | — | — |
| rehearsal_v3_20260805T112524Z | 1 | 21 | 0xA815 | 0xA815 | -0.008333333 |
| rehearsal_v4_20260805T131900Z | 1 | 21 | 0xA815 | 0xA815 | -0.008333333 |
| rehearsal_v4_20260805T131900Z | 2 | 21 | 0xA82A | 0xA82A | -0.008333333 |
| transport_fault_rehearsal_20260807T010100Z | none | 0 | — | — | — |
| transport_fault_rehearsal_20260807T061524Z | none | 0 | — | — | — |
| transport_fault_rehearsal_v2_20260807T062625Z | none | 0 | — | — | — |
| transport_fault_rehearsal_v3_20260807T064240Z | none | 0 | — | — | — |
| transport_fault_rehearsal_v4_20260807T064359Z | none | 0 | — | — | — |
| transport_fault_rehearsal_v5_20260807T065642Z | none | 0 | — | — | — |

### Response classifications

| Run | Request | Post-error (Hz) | Observed response (Hz) | Class |
| --- | --- | --- | --- | --- |
| campaign_a_20260803T125400Z | 1 | 0.041666666 | 0 | measurement_or_actuator_fault |
| campaign_a_v2_20260803T170039Z | 1 | 0.041666666 | -0.003333334 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 1 | 0.041666666 | -0.005000001 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 2 | 0.038333334 | -0.003333332 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 3 | 0.035 | -0.003333334 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 4 | 0.029999999 | -0.005000001 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 5 | 0.028333334 | -0.003333332 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 6 | 0.023333333 | -0.005000001 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 7 | 0.02 | -0.005000001 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 8 | 0.018333333 | -0.003333334 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 9 | 0.013333334 | -0.003333334 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 10 | 0.01 | -0.005000001 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 11 | 0.006666666 | -0.003333334 | healthy_detected |
| campaign_a_v3_20260803T183120Z | 12 | 0.003333334 | -0.003333332 | inside_deadband |
| campaign_b_20260804T022822Z | 1 | -0.008333333 | 0.003333334 | healthy_detected |
| campaign_b_20260804T022822Z | 2 | -0.005000001 | 0.003333332 | inside_deadband |
| active_hil_rehearsal_v6_20260807T065805Z | 1 | -0.008333333 | 0 | healthy_indeterminate_near_resolution |
| active_hil_rehearsal_v6_20260807T065805Z | 2 | 0 | 0.008333333 | inside_deadband |
| part_a2_20260805T113912Z | 1 | -0.006666666 | 0.003333334 | healthy_detected |
| part_b_20260805T140241Z | 1 | -0.003333334 | 0.003333332 | inside_deadband |
| part_b_final_20260807T073432Z | 1 | -0.005000001 | 0.001666665 | inside_deadband |
| part_b_retry_20260806T050640Z | 1 | -0.003333334 | 0.003333332 | inside_deadband |
| rehearsal_service_arm_20260806T042537Z | 1 | -0.008333333 | 0.008333335 | healthy_detected |
| rehearsal_service_arm_20260806T042537Z | 2 | -0.008333333 | 0 | healthy_detected |
| rehearsal_v3_20260805T112524Z | 1 | -0.008333333 | 0 | healthy_indeterminate_near_resolution |
| rehearsal_v4_20260805T131900Z | 1 | 0 | 0.008333333 | inside_deadband |
| rehearsal_v4_20260805T131900Z | 2 | -0.008333333 | 0 | healthy_indeterminate_near_resolution |

### Complete transaction record sequences

| Run | Records | Ordered events |
| --- | --- | --- |
| campaign_a_20260803T125400Z | 4 | manual_start → request_accepted → application → response |
| campaign_a_v2_20260803T170039Z | 4 | manual_start → request_accepted → application → response |
| campaign_a_v3_20260803T183120Z | 37 | manual_start → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response → request_accepted → application → response |
| device_abort_smoke_20260803T125100Z | 0 | none |
| out_of_model_passive_a93b_20260803T140906Z | 0 | none |
| rapid_step_characterization_20260803T141658Z | 0 | none |
| campaign_b_20260804T022822Z | 7 | manual_start → request_accepted → application → response → request_accepted → application → response |
| active_hil_rehearsal_v3_20260807T061811Z | 0 | none |
| active_hil_rehearsal_v4_20260807T062941Z | 0 | none |
| active_hil_rehearsal_v5_20260807T064546Z | 1 | manual_start |
| active_hil_rehearsal_v6_20260807T065805Z | 9 | manual_start → request_created → core0_accepted → application → response → request_created → core0_accepted → application → response |
| part_a2_20260805T065551Z | 2 | manual_start → request_created |
| part_a2_20260805T084537Z | 1 | manual_start |
| part_a2_20260805T090847Z | 4 | manual_start → request_created → core0_accepted → application |
| part_a2_20260805T113912Z | 6 | manual_start → request_created → core0_accepted → application → response → request_created |
| part_a_20260804T142912Z | 0 | none |
| part_a_20260804T150342Z | 1 | manual_start |
| part_a_20260804T161646Z | 1 | manual_start |
| part_a_20260804T174201Z | 1 | manual_start |
| part_a_20260804T191214Z | 1 | manual_start |
| part_a_20260804T204214Z | 1 | manual_start |
| part_a_20260804T222508Z | 1 | manual_start |
| part_b_20260805T140241Z | 5 | manual_start → request_created → core0_accepted → application → response |
| part_b_final_20260807T073432Z | 5 | manual_start → request_created → core0_accepted → application → response |
| part_b_retry_20260806T050640Z | 5 | manual_start → request_created → core0_accepted → application → response |
| rehearsal_20260805T104402Z | 1 | manual_start |
| rehearsal_service_arm_20260806T042537Z | 9 | manual_start → request_created → core0_accepted → application → response → request_created → core0_accepted → application → response |
| rehearsal_v2_20260805T111805Z | 0 | none |
| rehearsal_v3_20260805T112524Z | 5 | manual_start → request_created → core0_accepted → application → response |
| rehearsal_v4_20260805T131900Z | 9 | manual_start → request_created → core0_accepted → application → response → request_created → core0_accepted → application → response |
| transport_fault_rehearsal_20260807T010100Z | 0 | none |
| transport_fault_rehearsal_20260807T061524Z | 0 | none |
| transport_fault_rehearsal_v2_20260807T062625Z | 0 | none |
| transport_fault_rehearsal_v3_20260807T064240Z | 0 | none |
| transport_fault_rehearsal_v4_20260807T064359Z | 0 | none |
| transport_fault_rehearsal_v5_20260807T065642Z | 0 | none |

## Exact active identities

| Run | Firmware source | Config | UF2 | Estimator | Model | Active policy | Response policy | Numerical policy | Shadow contract |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| campaign_a_20260803T125400Z | 93703a198678b05c18b054d6c815d55a567710013c32b8ff01186d693b4f1fab | b6092e818d2bb5d05389fac365e3496eb16dad99f7869f9de87a23dd91562ed7 | b87139796da2f0ce7e4355e4b6f66bc460f8fb97d5b3e0af010309cc0498be13 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | d8fbc3539759be1de60d6b4507a50f029b3eaf830952b65ddb4c9849992ef8dd | 657df688c8e6b1bce1ac8280b46e5388ee1d6dfbe31e34735611c933ca4f261e | 0a7ec7b8f569da4a233c03e56c42bd7bd522ca1c27e97d4028b6c52a2ecfe963 | 19cddd7cb169c4c733b7cfd69085f9ecc087ad77a874f265c4c7c0f053aced43 | None |
| campaign_a_v2_20260803T170039Z | 5ac64323fdd0e4f3327f797fb8d4e7bfeb52750caf4ec194cc58e7616a0ea150 | b1bdeb2a751874d783672e1532184e7443a8543350cb6b1c68e9e4462ee3aeab | 312cea357c2627e3f26a09d7cd14dd2b2797169e1ee83b43af235850bfa9ec7c | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | None |
| campaign_a_v3_20260803T183120Z | ea8216052248f796bf514c588409f765ddb946f615703b32069f7f328e765df2 | b1bdeb2a751874d783672e1532184e7443a8543350cb6b1c68e9e4462ee3aeab | edb1bb6b9a202110a6b9de410328f40aeafd6dcf7e8617e04cf4552c583957cd | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | None |
| device_abort_smoke_20260803T125100Z | 93703a198678b05c18b054d6c815d55a567710013c32b8ff01186d693b4f1fab | b6092e818d2bb5d05389fac365e3496eb16dad99f7869f9de87a23dd91562ed7 | b87139796da2f0ce7e4355e4b6f66bc460f8fb97d5b3e0af010309cc0498be13 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | d8fbc3539759be1de60d6b4507a50f029b3eaf830952b65ddb4c9849992ef8dd | 657df688c8e6b1bce1ac8280b46e5388ee1d6dfbe31e34735611c933ca4f261e | 0a7ec7b8f569da4a233c03e56c42bd7bd522ca1c27e97d4028b6c52a2ecfe963 | 19cddd7cb169c4c733b7cfd69085f9ecc087ad77a874f265c4c7c0f053aced43 | None |
| out_of_model_passive_a93b_20260803T140906Z | 93703a198678b05c18b054d6c815d55a567710013c32b8ff01186d693b4f1fab | b6092e818d2bb5d05389fac365e3496eb16dad99f7869f9de87a23dd91562ed7 | b87139796da2f0ce7e4355e4b6f66bc460f8fb97d5b3e0af010309cc0498be13 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | d8fbc3539759be1de60d6b4507a50f029b3eaf830952b65ddb4c9849992ef8dd | 657df688c8e6b1bce1ac8280b46e5388ee1d6dfbe31e34735611c933ca4f261e | 0a7ec7b8f569da4a233c03e56c42bd7bd522ca1c27e97d4028b6c52a2ecfe963 | 19cddd7cb169c4c733b7cfd69085f9ecc087ad77a874f265c4c7c0f053aced43 | None |
| rapid_step_characterization_20260803T141658Z | 93703a198678b05c18b054d6c815d55a567710013c32b8ff01186d693b4f1fab | 400de0c9008a36c8dc6229070caf31fd64eb24fc587640d3546fcf0acb6446f8 | cbf0a4eb1eba8b5d1dc6e1e75368101f53c85c50cf060cbff2606c6a3da9e5c7 | None | None | None | None | None | None |
| campaign_b_20260804T022822Z | ea8216052248f796bf514c588409f765ddb946f615703b32069f7f328e765df2 | 075c78108b5749d317326fd0a25da1f6323c6d055c4c8137b0ea76ea4c46f401 | f5f8be0c1d808df3e917c8a80a74e028abd9cd0b879321e8417184d0449cfbd4 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | None |
| active_hil_rehearsal_v3_20260807T061811Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| active_hil_rehearsal_v4_20260807T062941Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| active_hil_rehearsal_v5_20260807T064546Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| active_hil_rehearsal_v6_20260807T065805Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| part_a2_20260805T065551Z | d8fdff7178bc899a6ac8073daab1f90cf3a44ddf43bdeffcbbd54824c40d0c4a | 18c8ba8579b813319a88d47dcf207c485475461dfe6d8b72c67e946e46fa5276 | e5212c5173ef40e4fc3b42e3bcf1daab259b7ad4d1a2fea4b90c0e5906863b03 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | c9336162e1c27bd037fa854cef33c0080b8fe1ebfaf24ff0302f2eae2c1e4291 |
| part_a2_20260805T084537Z | 16d3ca72d81a51a5f7776f7759efeb8a3c8c6d709a239e6b062ecabf05d25986 | 18c8ba8579b813319a88d47dcf207c485475461dfe6d8b72c67e946e46fa5276 | 688600b3a6869b76d56311505a54800619262a2d4a2150c37d1f70386eeda551 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | bcf89ecfa1b926a54aaf6f2518e26283ff8263e93e8cd31444057da8651972c1 |
| part_a2_20260805T090847Z | 16d3ca72d81a51a5f7776f7759efeb8a3c8c6d709a239e6b062ecabf05d25986 | 18c8ba8579b813319a88d47dcf207c485475461dfe6d8b72c67e946e46fa5276 | 688600b3a6869b76d56311505a54800619262a2d4a2150c37d1f70386eeda551 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | bcf89ecfa1b926a54aaf6f2518e26283ff8263e93e8cd31444057da8651972c1 |
| part_a2_20260805T113912Z | 9bdf71ccac8ddca19c637a0baa33a2ea67f6e1ee05595e1dd9cc5191a732cc7f | 0bf46da8073349967d99622e4dc0399cbd7e8fe27e17f1d608923b91d6a73b98 | f96f27047f9ad77e1b940813ccfda6d9f535fafbff392b04f4a5a551df11ee29 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | bcf89ecfa1b926a54aaf6f2518e26283ff8263e93e8cd31444057da8651972c1 |
| part_a_20260804T142912Z | 73881e344f102ce8b66668f703d12fb453204c63aadc3746efcb9f3de2729aa1 | f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0 | 52c66b2254823a3ed2148dec98c20e3662cae5b9bf1a3c1e43e50bb2618d9a55 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | 85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9 |
| part_a_20260804T150342Z | 6939d8334cae87acf28897b1001a84568a52a56467378bff4963213ac8e619ca | f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0 | 454f211c9bf995b38711d5ad5656f46b75924c4a80d7a3efb1c8681f26eae20e | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | 85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9 |
| part_a_20260804T161646Z | f297831f9e27302a04b75a8d386fa77a11fe49edc47b14becc40c6191a13daa6 | f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0 | 288ad4885a59074c75af092b3ac654f14d946859e3316d925b086c2298ed854f | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | 85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9 |
| part_a_20260804T174201Z | 969d71ab90a5df8d7ec030f8baec8f93a38a90d24e7c1ccadc1548cdf0e6794c | f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0 | b5f0f0af5cf3e0fb2dc6441e5fb5a2a4f1a5b4900a35ac69db3107bd4dbd65e2 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | 85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9 |
| part_a_20260804T191214Z | 969d71ab90a5df8d7ec030f8baec8f93a38a90d24e7c1ccadc1548cdf0e6794c | f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0 | bf90746dbb9a51c7bbbd2deedba43d9e9ab213d0aadb77a850ab3e8a5a053a04 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | 85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9 |
| part_a_20260804T204214Z | 969d71ab90a5df8d7ec030f8baec8f93a38a90d24e7c1ccadc1548cdf0e6794c | f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0 | 0bda0284b8dcd0b19680e4f0384feff1076ccd9a9a8abfa7c267fbd05942a139 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | 85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9 |
| part_a_20260804T222508Z | 8028451400d7bd65c50aa1379cc3b05a942e2e9da352ed5cbe7c2a0c0bad2381 | f3e4ebac336bf6892064f662b77d54698f8c2b5d3c03113749f7a63d843e23f0 | 32afcf50a8077a154bc3428ba552db64b39f3cddfdc7fd725f1d62d21e800627 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | 85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9 |
| part_b_20260805T140241Z | 7d2f6a01bdc6ca3578f06fec343a5a4611385e8d0f74c06a08b5f38aae3ac9cc | 70702906c08be11ec5ec3f2ba9795710cb36c5a2caa22141cd151e3ad96c4c8b | 4c30bfa44f47d759158590e182bb5905130e04da334ccf6d5e314be4c00ca3f1 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | bcf89ecfa1b926a54aaf6f2518e26283ff8263e93e8cd31444057da8651972c1 |
| part_b_final_20260807T073432Z | fdcb2205f4e4db5848c01bec55cdb3089c0908db613de48277c434aaa15da875 | 70702906c08be11ec5ec3f2ba9795710cb36c5a2caa22141cd151e3ad96c4c8b | ab14664ace5ff2e6a9de77f4754e1d3077d502db9008f4299352134ae89258fb | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | bcf89ecfa1b926a54aaf6f2518e26283ff8263e93e8cd31444057da8651972c1 |
| part_b_retry_20260806T050640Z | b30ed8c661cccfbf9a1a103cd636d59ca0b36baa3d88cec72da0a58a49dbdddc | 70702906c08be11ec5ec3f2ba9795710cb36c5a2caa22141cd151e3ad96c4c8b | 8fbe2a1420652f848f1c6c9d408679b397579249f766981fb2ff8adea439afc5 | 5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | 29db33da6a518727b25396f5fa77e26a1f5ca886a7eda232ca32997c5e82ae42 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | a5151f2fa3462e6b7dbd5d0562fd8a7ea94220e72ac2dfaf808f474ded765521 | bcf89ecfa1b926a54aaf6f2518e26283ff8263e93e8cd31444057da8651972c1 |
| rehearsal_20260805T104402Z | 3e08ffc3a960dabf5da3717ba71911521d0fc3f659078a9b26443a8253d3d7b6 | 371419bbe77dd2d7d9f119231c31ada4db5921ec2ddce5e8b8bf0a829d5e6b11 | 70e6a0c95ebba3ef80c3dc4fe9d058c0bb117ba01d994ff8e8b99eb2ba9c234e | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | c8db270d92e5045fc3b03f7d1ea607da1ea145478b49c300bc6af9987c538d8d | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | c8db270d92e5045fc3b03f7d1ea607da1ea145478b49c300bc6af9987c538d8d | None |
| rehearsal_service_arm_20260806T042537Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 6220969c0b2f2a45fc469272b06bae62d75e33f7e0acbbb5429d4ce0cd5a7ada | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| rehearsal_v2_20260805T111805Z | 4282d4d8d270537bb2f7661a0cd8919e69f46d23b35e6e55639113feab183f99 | 30c12a9c0acbe663c293e3fc71791cf52d6d7ac8584b6f9e9fe44870f7acbf06 | 1857edaceacf66a367eb66deb9cc1114fddf219bcef726295a6cc14532d5cf9a | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | eef8f40b370c148fce8795c0a7f372132f2409d694d73ac3ae1af0c3935cc165 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | eef8f40b370c148fce8795c0a7f372132f2409d694d73ac3ae1af0c3935cc165 | None |
| rehearsal_v3_20260805T112524Z | 9bdf71ccac8ddca19c637a0baa33a2ea67f6e1ee05595e1dd9cc5191a732cc7f | 30c12a9c0acbe663c293e3fc71791cf52d6d7ac8584b6f9e9fe44870f7acbf06 | 5c518c13ad9a94fce463be185a79e86d023180cb0c0c95edb8d9c3e43bc48994 | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | eef8f40b370c148fce8795c0a7f372132f2409d694d73ac3ae1af0c3935cc165 | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | eef8f40b370c148fce8795c0a7f372132f2409d694d73ac3ae1af0c3935cc165 | None |
| rehearsal_v4_20260805T131900Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | b2eca70d96a70478e7515d1eaa50805bb0a6e3b67dba2b85a6bdb1497a57c118 | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| transport_fault_rehearsal_20260807T010100Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| transport_fault_rehearsal_20260807T061524Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| transport_fault_rehearsal_v2_20260807T062625Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| transport_fault_rehearsal_v3_20260807T064240Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| transport_fault_rehearsal_v4_20260807T064359Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |
| transport_fault_rehearsal_v5_20260807T065642Z | d891345bb005fe750dea9867235c8e5a75b1c47c3a9cf6282868132068b9816f | a3f0baf993085538ff6d3b477efb9e25d8cc1a96366f66eddd4f8cc8604060be | 87258a65623a818a0b7cf18bdb97b465cd84e2bea5b33231ae05751965ff11ea | 54173f493cb7dc459e57e7695d98b518a2616ded914898647f459b2325c94977 | 5d5d01f794294f9d066670f0547962df6752c2abfdb7261d3d21dbe36ee6a6e1 | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | f3c30171af6d7a7bb4c560385f7253ddbe61ad29f9e1111f46263bbfb61324ec | d73f3d94454f319229b4a0601877cd3529d9fd8cb2a87b3a86fb2bfcdbdaf6bf | None |

## Frequency-control and deadband evidence

The authoritative Stage 7 policy retained the V2 deadband of `abs(error) <= 0.006249995628992717 Hz`; shadow candidates had zero authority.

| Metric | Measured value |
| --- | --- |
| qualified 600 s observations | 151 |
| minimum error (Hz) | -0.006666665897 |
| maximum error (Hz) | -0.00166666694 |
| mean error (Hz) | -0.0030905082207748342 |
| median error (Hz) | -0.00333333388 |
| inside-deadband fraction | 0.9933774834437086 |
| boundary crossings | 1 |
| longest continuous inside residence (s) | 90000.0 |
| linear drift (Hz/s) | 1.0711703245484988e-08 |
| effective sample size | 151.0 |
| automatic applications | 1 |
| absolute path (codes) | 19 |
| net movement (codes) | 19 |
| direction-paired hysteresis | unresolved_inadequate_natural_direction_paired_support |

Full fixed-code distributions, residence segments, autocorrelation, Newey–West uncertainty, service/environment associations, candidate replay, dither and hysteresis records remain verbatim in the immutable Stage 7B gate listed above.

## GNSS validity and availability

Stage 7B qualified 151 of 151 authoritative observations; its longest unqualified run was 0 selected estimates.
Receiver metadata qualifies but does not timestamp the hardware PPS. Fix quality, GSA-3D, checksum, identity, controlled Stage 6 invalidation/recovery and any natural outage evidence remain bounded to eligibility; none supplies UTC traceability.

## Cross-core architecture and isolation

Core 1 owns timing, observation, estimation and request generation; Core 0 owns USB, GNSS/environment service and physical I2C application. Stage 6 and Stage 7 evidence must both pass before the endurance decision can be selected.

Stage 7B recorded 1 complete cross-core transaction latency sets, 1/1 complete four-phase request groups, and exact response replay=True.

## Faults, stops, recovery and preservation

Every manifest-bearing active attempt appears in the correction-history table, including diagnostic and stopped runs. Passing runs cannot erase a failed prefix; diagnostic evidence remains explicitly non-passing.

## Final software/build verification

| Gate | Result | Exact outcome |
| --- | --- | --- |
| pytest | pass | passed=790 skipped=2 failed=0 errors=0 |
| firmware matrix | pass | supported=22/22 guarded=7/7 |
| no-hardware validation | pass | integrated script exited 0 after the full pytest suite, all 29 firmware-matrix profiles, three wire fixtures, and synthetic validate_run/report_run |

## Remaining blockers and unsupported claims

- no calibrated absolute-frequency accuracy or combined uncertainty claim
- no UTC traceability, phase lock or holdover claim
- no oscilloscope-based D8 waveform, rise/fall or phase-margin qualification
- nearby-air SHT41 data remains a covariate, not a demonstrated CX317 case-temperature model
- the GNSS receiver is read-only and not a timing-grade provisioned receiver

## Recommended next programme

Recommend exactly one goal: `phase_estimator_definition_and_bounded_hybrid_phase_frequency_preview`.

Frequency acquisition and dual-core endurance are established; the largest remaining control-function gap is a replayable phase estimator and a non-actionable bounded hybrid preview.

This recommendation grants no actuation authority. A new programme must freeze its estimator, replay, limits and hardware gates separately.

## Final static state

Last confirmed applied code: `0xA828`. Leave it static; Stage 8 performs no DAC write.
