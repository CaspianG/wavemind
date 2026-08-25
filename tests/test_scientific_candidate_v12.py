from wavemind.scientific_memoryagentbench import official_primary_metric


def test_v12_primary_metric_routing_depends_only_on_official_source_name():
    assert official_primary_metric("detective_qa") == "exact_match"
    assert official_primary_metric("recsys_redial_full") == "recsys_recall@10"
    assert official_primary_metric("ruler_niah") == "ruler_recall"
    assert official_primary_metric("eventqa_65536") == "substring_exact_match"
    assert official_primary_metric("longmemeval_s") == "substring_exact_match"


def test_v13_summarization_routes_to_official_rouge_l_recall():
    assert official_primary_metric("infbench_sum_eng_shots2") == "rougeL_recall"
