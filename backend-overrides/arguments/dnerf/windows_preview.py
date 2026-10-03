# A short visual preview on the 16 GB laptop GPU; not paper convergence.
_base_ = './bouncingballs.py'
OptimizationParams = dict(
    coarse_iterations=300,
    iterations=3000,
    batch_size=1,
    dataloader=False,
    densify_until_iter=2500,
    render_process=False,
)
