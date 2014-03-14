#!/usr/bin/env python

from pyparsing import *

name = Word(alphas)
number = Word(nums)('number').setParseAction(lambda t: [Number(t[0])])
variable = Word(alphas).setParseAction(lambda t: [Variable(t[0])])
atom = variable | number

expr = Forward()
ifexp = Group(Keyword("if") + expr + Keyword("then") + expr + Keyword("else") + expr)('if').setParseAction(lambda t: [If(t[0][1], t[0][3], t[0][5])])
fexp = Group(name + Literal("(").suppress() + ZeroOrMore(expr) + Literal(")").suppress()).setParseAction(lambda t: [Call(t[0][0], t[0][1:])])
paren = Group(Literal("(").suppress() + expr + Literal(")").suppress())

aexp = ifexp | fexp | atom | paren

op = Group(aexp + oneOf("+ - * / <") + expr).setParseAction(lambda t: [BinaryOperator(t[0][1], t[0][0], t[0][2])])

expr << ( op | aexp)

fdef = Group(Keyword("def") + name + Literal("(").suppress() + Group(ZeroOrMore(name)) + Literal(")").suppress() + expr).setParseAction(lambda t: [FunctionDef(t[0][1], t[0][2], t[0][3])])

program = OneOrMore(fdef | expr)


from llvm.core import Module, Constant, Type, Function, Builder, FCMP_ULT
from llvm.core import FCMP_ULT, FCMP_ONE


class Expression(object):
    pass

class Number(Expression):
    
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return "Number({})".format(self.value)

    def gen_code(self, module, builder, variables):
        return Constant.real(Type.double(), self.value)

class Variable(Expression):

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return "Variable({})".format(self.name)

    def gen_code(self, module, builder, variables):
        return variables[self.name]

class If(Expression):

    def __init__(self, condition, then_value, else_value):
        self.condition = condition
        self.then_branch = then_value
        self.else_branch = else_value

    def __repr__(self):
        return "If({}, {}, {})".format(self.condition, self.then_branch, self.else_branch)

    def gen_code(self, module, builder, variables):
        condition = self.condition.gen_code(module, builder, variables)
        condition_bool = builder.fcmp(FCMP_ONE, condition, Constant.real(Type.double(), 0), 'ifcond')
        function = builder.basic_block.function
        then_block = function.append_basic_block('then')
        else_block = function.append_basic_block('else')
        merge_block = function.append_basic_block('ifcond')
        builder.cbranch(condition_bool, then_block, else_block)
        builder.position_at_end(then_block)
        then_value = self.then_branch.gen_code(module, builder, variables)
        builder.branch(merge_block)
        then_block = builder.basic_block
        builder.position_at_end(else_block)
        else_value = self.else_branch.gen_code(module, builder, variables)
        builder.branch(merge_block)
        else_block = builder.basic_block
        builder.position_at_end(merge_block)
        phi = builder.phi(Type.double(), 'iftmp')
        phi.add_incoming(then_value, then_block)
        phi.add_incoming(else_value, else_block)
        return phi

class Call(Expression):

    def __init__(self, callee, args):
        self.callee = callee
        self.args = args

    def __repr__(self):
        return "Call({}, {})".format(self.callee, self.args)

    def gen_code(self, module, builder, variables):
        callee = module.get_function_named(self.callee)
        arg_values = [i.gen_code(module, builder, variables) for i in self.args]
        return builder.call(callee, arg_values, 'calltmp')

class BinaryOperator(Expression):

    def __init__(self, operator, lhs, rhs):
        self.operator = operator
        self.lhs = lhs
        self.rhs = rhs

    def __repr__(self):
        return "BinaryOperator({}, {}, {})".format(self.operator, self.lhs, self.rhs)

    def gen_code(self, module, builder, variables):
        left = self.lhs.gen_code(module, builder, variables)
        right = self.rhs.gen_code(module, builder, variables)

        if self.operator == '+':
            return builder.fadd(left, right, 'addtmp')
        elif self.operator == '-':
            return builder.fsub(left, right, 'subtmp')
        elif self.operator == '*':
            return builder.fmul(left, right, 'multmp')
        elif self.operator == '/':
            return builder.fdiv(left, right, 'divtmp')
        elif self.operator == '<':
            result = builder.fcmp(FCMP_ULT, left, right, 'cmptmp')
            return builder.uitofp(result, Type.double(), 'booltmp')
        else:
            raise RuntimeError('Unknown binary operator.')

class FunctionDef(object):

    def __init__(self, name, args, body):
        self.name = name
        self.args = args
        self.body = body

    def __repr__(self):
        return "Function({}, {}, {})".format(self.name, self.args, self.body)

    def gen_code(self, module, builder, variables):
        funct_type = Type.function(Type.double(), [Type.double()] * len(self.args), False)
        function = Function.new(module, funct_type, self.name)

        variables = {}
        for arg, arg_name in zip(function.args, self.args):
            arg.name = arg_name
            variables[arg_name] = arg

        block = function.append_basic_block('entry')

        builder = Builder.new(block)

        return_value = self.body.gen_code(module, builder, variables)
        builder.ret(return_value)

        function.verify()

        return function

test = """
def fib(n) if n < 3 then 1 else fib(n-1) + fib(n-2)
def div(a b) a/b
fib(40)
"""

module = Module.new('sfpl')

from pprint import *

res = program.parseString(test, parseAll=True)
pprint(res.asList())

funs = [x.gen_code(module, None, None) for x in res[:-1]]
fun = FunctionDef('', [], res[-1]).gen_code(module, None, None)

from llvm.ee import ExecutionEngine, TargetData

g_llvm_executor = ExecutionEngine.new(module)

ret = g_llvm_executor.run_function(fun, [])
print ret.as_real(Type.double())
