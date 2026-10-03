# Short end-to-end validation, not the paper's convergence configuration.
_base_ = './bouncingballs.py'
OptimizationParams = dict(
    coarse_iterations=100,
    iterations=200,
    batch_size=1,
    dataloader=False,
    densify_until_iter=0,
    render_process=False,
)
