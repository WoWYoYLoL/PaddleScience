# Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import paddle
from regex import D

import ppsci
from ppsci.autodiff import hessian
from ppsci.autodiff import jacobian
from ppsci.utils import config
from ppsci.utils import logger

if __name__ == "__main__":
    args = config.parse_args()
    # enable computation for fourth-order differentiation of matmul
    paddle.fluid.core.set_prim_eager_enabled(True)
    # set random seed for reproducibility
    ppsci.utils.misc.set_random_seed(42)
    # set training hyper-parameters
    iters_per_epoch = 1
    epochs = 10000 if not args.epochs else args.epochs
    # set output directory
    output_dir = "./output/euler_beam" if not args.output_dir else args.output_dir
    # initialize logger
    logger.init_logger("ppsci", f"{output_dir}/train.log", "info")

    # set model
    model = ppsci.arch.MLP(("x",), ("u",), 3, 20)

    # set geometry
    geom = {"interval": ppsci.geometry.Interval(0, 1)}

    # set equation(s)
    equation = {"biharmonic": ppsci.equation.pde.Biharmonic(dim=1, q=-1.0, D=1.0)}

    # set dataloader config
    dataloader_cfg = {
        "dataset": "IterableNamedArrayDataset",
        "iters_per_epoch": iters_per_epoch,
    }
    # set constraint
    pde_constraint = ppsci.constraint.InteriorConstraint(
        equation["biharmonic"].equations,
        {"biharmonic": 0},
        geom["interval"],
        {**dataloader_cfg, "batch_size": 100},
        ppsci.loss.MSELoss(),
        random="Hammersley",
        name="EQ",
    )
    bc = ppsci.constraint.BoundaryConstraint(
        {
            "u0": lambda d: d["u"][0:1],
            "u__x": lambda d: jacobian(d["u"], d["x"])[1:2],
            "u__x__x": lambda d: hessian(d["u"], d["x"])[2:3],
            "u__x__x__x": lambda d: jacobian(hessian(d["u"], d["x"]), d["x"])[3:4],
        },
        {"u0": 0, "u__x": 0, "u__x__x": 0, "u__x__x__x": 0},
        geom["interval"],
        {**dataloader_cfg, "batch_size": 4},
        ppsci.loss.MSELoss("sum"),
        evenly=True,
        name="BC",
    )

    # wrap constraints together
    constraint = {
        pde_constraint.name: pde_constraint,
        bc.name: bc,
    }

    # set optimizer
    optimizer = ppsci.optimizer.Adam(learning_rate=0.001)((model,))

    def u_solution_func(out):
        """compute ground truth for u as label data"""
        x = out["x"]
        return -(x**4) / 24 + x**3 / 6 - x**2 / 4

    # set validator
    total_size = 100
    l2_rel_metric = ppsci.validate.GeometryValidator(
        {"u": lambda out: out["u"]},
        {"u": u_solution_func},
        geom["interval"],
        {
            "dataset": "IterableNamedArrayDataset",
            "total_size": total_size,
        },
        ppsci.loss.MSELoss(),
        evenly=True,
        metric={"L2Rel": ppsci.metric.L2Rel()},
        name="L2Rel_Metric",
    )
    validator = {l2_rel_metric.name: l2_rel_metric}

    # set visualizer(optional)
    visu_points = geom["interval"].sample_interior(total_size, evenly=True)
    visualizer = {
        "visulzie_u": ppsci.visualize.VisualizerScatter1D(
            visu_points,
            ("x",),
            {"u": lambda d: d["u"]},
            1,
            "result_u",
        )
    }

    # initialize solver
    solver = ppsci.solver.Solver(
        model,
        constraint,
        output_dir,
        optimizer,
        epochs=epochs,
        iters_per_epoch=iters_per_epoch,
        eval_during_train=True,
        eval_freq=1000,
        equation=equation,
        geom=geom,
        validator=validator,
        visualizer=visualizer,
    )
    # train model
    solver.train()
    # evaluate after finished training
    solver.eval()
    # visualize prediction after finished training
    solver.visualize()

    # directly evaluate model from pretrained_model_path(optional)
    logger.init_logger("ppsci", f"{output_dir}/eval.log", "info")
    solver = ppsci.solver.Solver(
        model,
        constraint,
        output_dir,
        equation=equation,
        validator=validator,
        visualizer=visualizer,
        pretrained_model_path=f"{output_dir}/checkpoints/best_model",
    )
    solver.eval()
    # visualize prediction from pretrained_model_path(optional)
    solver.visualize()
