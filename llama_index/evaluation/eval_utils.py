"""Get evaluation utils.

NOTE: These are beta functions, might change.

"""

from llama_index.indices.query.base import BaseQueryEngine
from llama_index.evaluation.base import EvaluationResult
import pandas as pd
import numpy as np
from typing import List, Any
import asyncio
from collections import defaultdict


def asyncio_module(show_progress: bool = False) -> Any:
    if show_progress:
        from tqdm.asyncio import tqdm_asyncio

        module = tqdm_asyncio
    else:
        module = asyncio

    return module


async def aget_responses(
    questions: List[str], query_engine: BaseQueryEngine, show_progress: bool = False
) -> List[str]:
    """Get responses."""
    tasks = []
    for question in questions:
        tasks.append(query_engine.aquery(question))
    asyncio_mod = asyncio_module(show_progress=show_progress)
    responses = await asyncio_mod.gather(*tasks)
    return responses


def get_responses(
    *args: Any,
    **kwargs: Any,
) -> List[str]:
    """Get responses.

    Sync version of aget_responses.

    """
    responses = asyncio.run(aget_responses(*args, **kwargs))
    return responses


def get_results_df(
    eval_results_list: List[EvaluationResult], 
    names: List[str], 
    metric_keys: List[str]
) -> pd.DataFrame:
    metric_dict = defaultdict(list)
    metric_dict["names"] = names
    for metric_key in metric_keys:
        for eval_results in eval_results_list:
            mean_score = np.array(
                [r.score for r in eval_results[metric_key]]
            ).mean()
            metric_dict[metric_key].append(mean_score)
    return pd.DataFrame(metric_dict)