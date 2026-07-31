const fs = require('fs')
const net = require('net')
const mineflayer = require('mineflayer')

const controls = JSON.parse(fs.readFileSync('./controls.json', 'utf8'))

const bot = mineflayer.createBot({
  host: 'localhost',
  port: 25565,
  username: 'MinecraftAI',
  auth: 'offline'
})

async function move(control, ticks = 8) {
  bot.setControlState(control, true)
  await bot.waitForTicks(ticks)
  bot.setControlState(control, false)
}

async function execute(action) {
  action = String(action).trim().toLowerCase()

  if (!controls.actions[action]) {
    console.log('Unknown action:', action)
    return
  }

  console.log('AI:', action)

  if (action === 'forward') await move('forward')
  else if (action === 'back') await move('back')
  else if (action === 'left') await move('left')
  else if (action === 'right') await move('right')
  else if (action === 'jump') await move('jump', 4)
  else if (action === 'stop') bot.clearControlStates()
  else if (action === 'turn_left') {
    await bot.look(bot.entity.yaw + 0.3, bot.entity.pitch, true)
  }
  else if (action === 'turn_right') {
    await bot.look(bot.entity.yaw - 0.3, bot.entity.pitch, true)
  }
  else if (action === 'look_up') {
    await bot.look(bot.entity.yaw, bot.entity.pitch - 0.2, true)
  }
  else if (action === 'look_down') {
    await bot.look(bot.entity.yaw, bot.entity.pitch + 0.2, true)
  }
  else if (action === 'mine') {
    const block = bot.blockAtCursor(5)
    if (block && bot.canDigBlock(block)) await bot.dig(block)
  }
  else if (action === 'attack') {
    const entity = bot.entityAtCursor(5)
    if (entity) bot.attack(entity)
  }
}

const server = net.createServer(socket => {
  console.log('Python AI connected')
  socket.setEncoding('utf8')
  let buffer = ''

  socket.on('data', data => {
    buffer += data

    let newline
    while ((newline = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, newline).trim()
      buffer = buffer.slice(newline + 1)
      if (!line) continue

      let action = line
      try {
        const message = JSON.parse(line)
        if (message.action) action = message.action
      } catch (_) {
        // Plain commands such as "forward" are also accepted.
      }

      execute(action).catch(console.error)
    }
  })
})

server.listen(5050, '127.0.0.1', () => {
  console.log('Controller listening on 127.0.0.1:5050')
})

bot.once('spawn', () => {
  console.log('Bot joined Minecraft as', bot.username)
})

bot.on('error', error => console.log('Minecraft error:', error.message))
bot.on('kicked', reason => console.log('Kicked:', reason))

process.on('SIGINT', () => {
  bot.clearControlStates()
  bot.quit('Controller stopped')
  server.close()
  process.exit(0)
})
