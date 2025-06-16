# from pyomo.environ import ConcreteModel, Var, Objective, SolverFactory

class Optimizador:
#     def ejecutar(self, gestor):
#         model = ConcreteModel()
#         model.x = Var(domain=float)

#         model.obj = Objective(expr=(model.x - 5)**2)  # objetivo simple

#         solver = SolverFactory('glpk')
#         result = solver.solve(model, tee=False)

#         gestor.resultados["optimization"] = {
#             "x_optimo": model.x.value
#         }
#         gestor.log(f"Etapa 3: Optimización completada (x = {model.x.value:.2f})")